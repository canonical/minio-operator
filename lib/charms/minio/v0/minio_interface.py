"""
Minio Interface

This Interface requires the serialized-data-interface package
please add it to your requirements.txt
"""
from provide_interface import ProvideAppInterface
from require_interface import RequireAppInterface

# The unique Charmhub library identifier, never change it
LIBID = "7d0810fb78cf4afd81cc70118b27a127"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft push-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2

# Serialized Data Schema for Minio Interface
MINIO_SCHEMA = """
service:
  type: string
port:
  type: number
access-key:
  type: string
secret-key:
  type: string
"""


class MinioProvide(ProvideAppInterface):
    SCHEMA = MINIO_SCHEMA


class MinioRequire(RequireAppInterface):
    SCHEMA = MINIO_SCHEMA
