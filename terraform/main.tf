resource "juju_application" "minio" {
  charm {
    name     = "minio"
    base     = var.base
    channel  = var.channel
    revision = var.revision
  }
  config             = var.config
  model              = var.model_name
  name               = var.app_name
  resources          = var.resources
  storage_directives = var.storage_directives
  trust              = true
  units              = 1
}
