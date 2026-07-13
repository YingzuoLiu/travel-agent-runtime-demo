# Cloud Runtime Upgrade

Version `0.3.0` adds a self-hosted execution-management layer around the travel application runtime. Version `0.4.0` adds a policy-enforced subprocess backend for registered tools.

## Architecture

```text
Client
  |
  v
FastAPI API
  |- /agent/message
  |- /runs
  `- /tools/{tool}/execute
         |
         v
RuntimeManager ---- AgentRegistry
  |
  +---- local worker queue
  |
  +----