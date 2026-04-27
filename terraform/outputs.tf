output "app_name" {
  value = juju_application.minio.name
}

output "provides" {
  value = {
    grafana_dashboard    = "grafana-dashboard",
    metrics_endpoint     = "metrics-endpoint",
    object_storage       = "object-storage",
    provide_cmr_mesh     = "provide-cmr-mesh",
    velero_backup_config = "velero-backup-config"
  }
}

output "requires" {
  value = {
    require_cmr_mesh = "require-cmr-mesh",
    service_mesh     = "service-mesh"
  }
}
