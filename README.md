## MinIO Operator

### Overview
This charm encompasses the Kubernetes operator for MinIO (see
[CharmHub](https://charmhub.io/?q=minio)).

The MinIO operator is a Python script that wraps the latest released MinIO, providing
lifecycle management for each application and handling events such as install, upgrade,
integrate, and remove.

## Install

To install MinIO, run:

    juju deploy minio

For more information, see https://juju.is/docs

## Gateway mode

Supported data storage services: s3, azure

To install MinIO in gateway mode for s3, run:

    juju deploy minio minio-s3-gateway \
        --config mode=gateway \
        --config gateway_storage_service=s3 \
        --config access-key=<aws_s3_access_key> \
        --config secret-key=<aws_s3_secret_key>

To install MinIO in gateway mode for azure, run:

    juju deploy minio minio-azure-gateway \
        --config mode=gateway \
        --config gateway_storage_service=azure \
        --config access-key=<azurestorageaccountname> \
        --config secret-key=<azurestorageaccountkey>

If you do not want to share your data storage service credentials with users,
you can create users in MinIO console with proper permissions for them.

For more information,
see: https://docs.min.io/docs/minio-multi-user-quickstart-guide.html

The credentials access-key and secret-key differs for Azure and AWS. Improper
credential error will be visible in container logs.

For more information, see: https://docs.min.io/docs/minio-gateway-for-azure.html
and https://docs.min.io/docs/minio-gateway-for-s3.html
