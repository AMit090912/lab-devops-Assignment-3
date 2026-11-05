output "network_name" {
  description = "Docker network created for the lab"
  value       = docker_network.lab.name
}

output "web_server_names" {
  description = "Names of the provisioned web containers"
  value       = docker_container.web[*].name
}

output "web_server_urls" {
  description = "URLs of the provisioned web servers"
  value       = [for idx in range(var.web_server_count) : "http://localhost:${var.web_base_port + idx}"]
}

output "ansible_inventory_file" {
  description = "Inventory generated for Ansible"
  value       = local_file.ansible_inventory.filename
}
