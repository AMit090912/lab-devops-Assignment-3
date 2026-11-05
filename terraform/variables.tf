variable "docker_host" {
  description = "Docker daemon address. Linux/WSL: unix:///var/run/docker.sock, Windows: npipe:////./pipe/docker_engine"
  type        = string
  default     = "unix:///var/run/docker.sock"
}

variable "project" {
  description = "Prefix used for every resource name"
  type        = string
  default     = "lab3"
}

variable "environment" {
  description = "Environment name (dev / staging / prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "web_server_count" {
  description = "Number of web server containers to provision"
  type        = number
  default     = 2

  validation {
    condition     = var.web_server_count >= 1 && var.web_server_count <= 5
    error_message = "web_server_count must be between 1 and 5."
  }
}

variable "web_base_port" {
  description = "First host port; server N is published on web_base_port + N"
  type        = number
  default     = 8081
}

variable "nginx_image" {
  description = "Pinned nginx image used for the web tier"
  type        = string
  default     = "nginx:1.27-alpine"
}
