# Lab 3 - Infrastructure provisioning with Terraform (Amit, 2301010471)
#
# Provisions a small web tier on the local Docker engine:
#   * an isolated Docker network
#   * N nginx web servers (count driven by a variable)
#   * an Ansible inventory file generated from the provisioned resources
#     (Terraform provisions -> Ansible configures)

locals {
  name_prefix = "${var.project}-${var.environment}"
  common_labels = {
    project     = var.project
    environment = var.environment
    managed_by  = "terraform"
    owner       = "amit-2301010471"
  }
}

resource "docker_network" "lab" {
  name   = "${local.name_prefix}-net"
  driver = "bridge"

  dynamic "labels" {
    for_each = local.common_labels
    content {
      label = labels.key
      value = labels.value
    }
  }
}

resource "docker_image" "nginx" {
  name         = var.nginx_image
  keep_locally = true
}

resource "docker_container" "web" {
  count   = var.web_server_count
  name    = "${local.name_prefix}-web-${count.index + 1}"
  image   = docker_image.nginx.image_id
  restart = "unless-stopped"

  ports {
    internal = 80
    external = var.web_base_port + count.index
  }

  networks_advanced {
    name = docker_network.lab.name
  }

  # Custom landing page so each server is identifiable
  upload {
    file    = "/usr/share/nginx/html/index.html"
    content = <<-HTML
      <!doctype html>
      <html><head><title>${local.name_prefix}-web-${count.index + 1}</title></head>
      <body>
        <h1>Provisioned by Terraform</h1>
        <p>Server: ${local.name_prefix}-web-${count.index + 1}</p>
        <p>Environment: ${var.environment}</p>
        <p>Owner: Amit (2301010471)</p>
      </body></html>
    HTML
  }

  healthcheck {
    test     = ["CMD", "wget", "-q", "-O", "/dev/null", "http://127.0.0.1/"]
    interval = "15s"
    timeout  = "5s"
    retries  = 3
  }

  dynamic "labels" {
    for_each = local.common_labels
    content {
      label = labels.key
      value = labels.value
    }
  }
}

# Terraform -> Ansible hand-off: generate the inventory from real resources
resource "local_file" "ansible_inventory" {
  filename        = "${path.module}/../ansible/inventory/terraform_web.ini"
  file_permission = "0644"

  content = templatefile("${path.module}/templates/inventory.tpl", {
    servers = [
      for idx, c in docker_container.web : {
        name = c.name
        port = var.web_base_port + idx
      }
    ]
  })
}
