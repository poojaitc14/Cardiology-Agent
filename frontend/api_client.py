"""API client for FastAPI backend communication."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import API_BASE_URL, API_TIMEOUT

logger = logging.getLogger(__name__)


class APIClient:
    """Client for communicating with the FastAPI backend."""

    def __init__(self, base_url: str = API_BASE_URL, timeout: int = API_TIMEOUT):
        """Initialize API client.
        
        Args:
            base_url: Base URL of the FastAPI server
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(timeout=timeout)

    def health_check(self) -> dict[str, Any]:
        """Check if API is healthy.
        
        Returns:
            Health status response
            
        Raises:
            httpx.RequestError: If request fails
        """
        try:
            response = self.client.get(f"{self.base_url}/health")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Health check failed: {e}")
            raise

    def query(self, patient_id: str, question: str) -> dict[str, Any]:
        """Submit a clinical query.
        
        Args:
            patient_id: Patient ID
            question: Clinical question
            
        Returns:
            Query response with answer, sources, tools_used, errors, trace_id
            
        Raises:
            httpx.RequestError: If request fails
            httpx.HTTPStatusError: If request returns error status
        """
        try:
            response = self.client.post(
                f"{self.base_url}/query",
                json={"patient_id": patient_id, "question": question},
            )
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Query request failed: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"Query returned error: {e.response.status_code} - {e.response.text}")
            raise

    def get_patient(self, patient_id: str) -> dict[str, Any]:
        """Get patient profile.
        
        Args:
            patient_id: Patient ID
            
        Returns:
            Patient profile data
            
        Raises:
            httpx.RequestError: If request fails
            httpx.HTTPStatusError: If patient not found or error occurs
        """
        try:
            response = self.client.get(f"{self.base_url}/patient/{patient_id}")
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Get patient request failed: {e}")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"Get patient returned error: {e.response.status_code}")
            raise

    def close(self):
        """Close the HTTP client."""
        self.client.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()


@staticmethod
def create_client(base_url: str = API_BASE_URL, timeout: int = API_TIMEOUT) -> APIClient:
    """Factory function to create API client.
    
    Args:
        base_url: Base URL of the FastAPI server
        timeout: Request timeout in seconds
        
    Returns:
        APIClient instance
    """
    return APIClient(base_url=base_url, timeout=timeout)
