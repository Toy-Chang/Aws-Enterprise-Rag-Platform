"""AWS adapters.

Each one implements the same port as its local counterpart, so the platform switches
backend by configuration and no service branches on where it is deployed:

======================  ==========================  ==========================
Port                    Local adapter               AWS adapter
======================  ==========================  ==========================
``DocumentStorage``     ``LocalFileSystemStorage``  :class:`S3DocumentStorage`
``EmbeddingModel``      ``HashingEmbeddingModel``   :class:`BedrockEmbeddingModel`
``VectorStore``         ``InMemoryVectorStore``     :class:`OpenSearchVectorStore`
======================  ==========================  ==========================

Every AWS SDK import is deferred until an adapter builds its own client, and every
adapter accepts an injected client, so the request and response mapping is tested
without an AWS account and the local deployment installs no AWS SDK at all.
"""

from __future__ import annotations

from app.aws.bedrock_embeddings import BedrockEmbeddingModel
from app.aws.opensearch_vector_store import OpenSearchVectorStore
from app.aws.s3_storage import S3DocumentStorage

__all__ = ["BedrockEmbeddingModel", "OpenSearchVectorStore", "S3DocumentStorage"]
