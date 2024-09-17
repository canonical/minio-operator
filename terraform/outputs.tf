output "app_name" {
  value = juju_application.minio.name
}

output "provides" {
  value = {
    object_storage    = "object-storage",
    metrics_endpoint  = "metrics-endpoint",
    grafana_dashboard = "grafana-dashboard"
  }
}
