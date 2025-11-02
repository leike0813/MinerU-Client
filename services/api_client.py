"""Thin HTTP client for the MinerU cloud API with retry-aware requests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.models import ApiError, UploadFile
from core.config import AppOptions
from services.logger import get_logger


logger = get_logger("api_client")


@dataclass
class BatchCreationResult:
    """Lightweight container returned after creating a batch."""

    batch_id: str
    file_urls: List[str]


class MinerUApiClient:
    """HTTP client wrapper for interacting with the MinerU API."""

    BASE_URL = "https://mineru.net/api/v4"

    def __init__(self, api_key: str, timeout: int = 30) -> None:
        """Configure a session with MinerU-specific headers and timeouts."""
        self._timeout = timeout
        self._session = self._build_session()
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    def _build_session(self) -> Session:
        """Return a requests session preloaded with exponential backoff retries."""
        session = requests.Session()
        retry = Retry(
            total=4,
            read=4,
            connect=4,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _handle_response(self, response: requests.Response) -> dict:
        """Decode JSON responses and raise descriptive errors when necessary."""
        if response.ok:
            try:
                return response.json()
            except json.JSONDecodeError as err:
                raise ApiError("Failed to parse API response", response.status_code) from err
        try:
            payload = response.json()
            message = payload.get("msg") or payload.get("message") or response.text
        except json.JSONDecodeError:
            payload = None
            message = response.text
        raise ApiError(message, response.status_code, payload)

    def create_batch(self, files: Iterable[UploadFile], options: AppOptions) -> BatchCreationResult:
        """Ask the API for upload URLs corresponding to the provided files."""
        payload = {
            "enable_formula": options.enable_formula,
            "enable_table": options.enable_table,
            "language": options.language,
            "files": [
                {
                    "name": file.display_name,
                    "is_ocr": options.is_ocr,
                }
                for file in files
            ],
        }

        logger.info("Creating batch for %d files", len(payload["files"]))
        response = self._session.post(
            f"{self.BASE_URL}/file-urls/batch",
            headers=self._headers,
            json=payload,
            timeout=self._timeout,
        )
        data = self._handle_response(response)

        if data.get("code") != 0:
            raise ApiError(data.get("msg", "Failed to create upload batch"), response.status_code, data)

        batch_id = data["data"]["batch_id"]
        file_urls = data["data"]["file_urls"]
        if len(file_urls) != len(payload["files"]):
            raise ApiError("API returned unexpected number of upload URLs", response.status_code, data)
        return BatchCreationResult(batch_id=batch_id, file_urls=file_urls)

    def upload_file(self, signed_url: str, file_path: Path) -> None:
        """Upload raw bytes to the signed storage URL provided by the API."""
        logger.debug("Uploading %s", file_path)
        with file_path.open("rb") as handle:
            response = self._session.put(
                signed_url,
                data=handle,
                timeout=self._timeout,
            )
        if not response.ok:
            raise ApiError(
                f"Failed to upload {file_path.name}",
                response.status_code,
                {"response": response.text},
            )

    def fetch_batch_status(self, batch_id: str) -> dict:
        """Query the API for the latest extraction state of a batch."""
        response = self._session.get(
            f"{self.BASE_URL}/extract-results/batch/{batch_id}",
            headers=self._headers,
            timeout=self._timeout,
        )
        data = self._handle_response(response)
        if data.get("code") not in (0, None):
            raise ApiError(data.get("msg", "Failed to fetch batch status"), response.status_code, data)
        return data

    def download_result(self, url: str) -> bytes:
        """Download the final ZIP bundle once parsing has finished."""
        response = self._session.get(url, timeout=self._timeout, stream=True)
        if not response.ok:
            raise ApiError("Failed to download result package", response.status_code, {"url": url})

        content = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                content.extend(chunk)
        return bytes(content)
