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

## MinIO console

Minio console is available under port 9001. To change this port use
configuration variable `console-port`, run:

    juju config minio console-port=9999

For more information,
see [minio-console documentation](https://docs.min.io/minio/baremetal/console/minio-console.html)

## Operation Modes

MinIO can be operated in the following modes:

* `server` (default): MinIO stores any data "locally", handling all aspects of the
  data storage within the deployed workload and storage in cluster
* `gateway`: MinIO works as a gateway to a separate blob storage (such as Amazon S3),
  providing an access layer to your data for in-cluster workloads

### Exmple using `gateway` mode

This charm supports using the following backing data storage services:
* s3
* azure

To install MinIO in gateway mode for s3, run:

    juju deploy minio minio-s3-gateway \
        --config mode=gateway \
        --config gateway-storage-service=s3 \
        --config access-key=<aws_s3_access_key> \
        --config secret-key=<aws_s3_secret_key>

To install MinIO in gateway mode for azure, run:

    juju deploy minio minio-azure-gateway \
        --config mode=gateway \
        --config gateway-storage-service=azure \
        --config access-key=<azurestorageaccountname> \
        --config secret-key=<azurestorageaccountkey>

In case of using private endpoints for storage service
specify `storage-endpoint-service`. This configuration is optional in case of
using S3 or Azure public endpoints.

By default, the backing storage credentials are also used as the credentials
to connect to the MinIO gateway itself.  If you do not want to share your 
data storage service credentials with users, you can create users in the
MinIO console with proper permissions for them.

For more information,
see: https://docs.min.io/docs/minio-multi-user-quickstart-guide.html

The credentials access-key and secret-key differs for Azure and AWS. Improper
credential error will be visible in container logs.

For more information, see: https://docs.min.io/docs/minio-gateway-for-azure.html
and https://docs.min.io/docs/minio-gateway-for-s3.html
