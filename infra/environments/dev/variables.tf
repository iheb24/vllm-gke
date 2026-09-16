variable "project_id" {
  description = "The GCP Project ID"
  type        = string
}

variable "my_public_ip" {
  description = "Your local public IP address (e.g., 203.0.113.5) for Master Authorized Networks"
  type        = string
}

variable "system_machine_type" {
  description = "Machine type for the always-on system node pool"
  type        = string
  default     = "e2-standard-4"
}
