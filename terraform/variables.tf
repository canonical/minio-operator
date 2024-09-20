variable "app_name" {
  description = "Application name"
  type        = string
  default     = "minio"
}

variable "channel" {
  description = "Charm channel"
  type        = string
  default     = null
}

variable "config" {
  description = "Map of charm configuration options"
  type        = map(string)
  default     = {}
}

variable "model_name" {
  description = "Model name"
  type        = string
}

variable "resources" {
  description = "Map of resources"
  type        = map(string)
  default     = null
}

variable "revision" {
  description = "Charm revision"
  type        = number
  default     = null
}

variable "storage_directives" {
  description = "Map of storage directives"
  type        = map(string)
  default     = null
}
