"""Shared, SigV4-authenticated OpenSearch client construction for OpenSearch Serverless.

OpenSearch Serverless has no username/password auth -- every request must be
SigV4-signed using the caller's AWS credentials (the same standard credential
chain boto3 already uses for DynamoDB) and the "aoss" service name.
"""
from __future__ import annotations

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection


def build_serverless_client(host: str, region: str) -> OpenSearch:
    """Build an OpenSearch client authenticated via AWS SigV4 for a Serverless collection.

    Args:
        host: The collection's bare endpoint hostname, e.g.
            "abc123xyz.eu-west-2.aoss.amazonaws.com" (no scheme/port -- both are
            fixed to https/443 for Serverless).
        region: AWS region the collection lives in.
    """
    bare_host = host.replace("https://", "").replace("http://", "").rstrip("/")
    credentials = boto3.Session().get_credentials()
    auth = AWSV4SignerAuth(credentials, region, "aoss")
    return OpenSearch(
        hosts=[{"host": bare_host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        pool_maxsize=20,
    )
