# Deepgram Self-Hosted on Modal

Deploy Deepgram's self-hosted Speech-to-Text (STT) and Text-to-Speech (TTS) services on [Modal](https://modal.com), a serverless GPU platform.

## Overview

This repository provides code and resources for deploying Deepgram's self-hosted API and Engine containers on Modal. Modal handles GPU provisioning, autoscaling, and networking, making it straightforward to run production Deepgram services without managing infrastructure directly.

### Architecture

Deepgram's self-hosted architecture consists of three services:

- **Engine (Impeller)**: GPU-powered inference service that performs speech processing
- **API (Stem)**: HTTP API that receives requests and forwards them to the Engine
- **License Proxy (Hermes)**: Caching proxy for license validation that enables high availability (optional but recommended for production)

This deployment runs all services in a single Modal container, communicating over localhost. The API is exposed via Modal's `http_server` decorator with regional proxy support for lower latency, while the Engine and License Proxy handle GPU inference and license validation internally.

## Quickstart and other documentation

See the [Quickstart guide](docs/1_introduction-and-quickstart.md) and other docs for step-by-step setup instructions and other information.
