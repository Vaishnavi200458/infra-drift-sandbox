terraform {
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

resource "docker_image" "nginx" {
  name         = "nginx:latest"
  keep_locally = false
}

resource "docker_network" "app_network" {
  name = "drift-network"
}

resource "docker_container" "web" {
  name  = "drift-web"
  image = docker_image.nginx.image_id

  ports {
    internal = 80
    external = 8080
  }

  networks_advanced {
    name = docker_network.app_network.name
  }
}

resource "docker_image" "redis" {
  name         = "redis:7-alpine"
  keep_locally = false
}

resource "docker_container" "cache" {
  name  = "drift-cache"
  image = docker_image.redis.image_id

  networks_advanced {
    name = docker_network.app_network.name
  }
}
