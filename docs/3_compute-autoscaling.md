# Compute and Autoscaling

With Modal, hardware resources and autoscaling configuration are specified as code. For the parameters in this section, update values by editing the values in `app.py` and redeploy.

When you clone the repo, the values are configured for an STT deployment in `us-west`.

```python
# modal_deepgram/app.py
GPU = "L4"
CPU_COUNT = 4
MEMORY = 32 * 1024  # MB
MIN_CONTAINERS = 1
TARGET_INPUTS = 64

# flash http_server deployments
PROXY_REGION = "us-west"
SERVER_REGION = ["us-west"]
```

## Configure hardware

Hardware is set as literals at the top of `modal_deepgram/app.py`, sized for STT (Nova family). Edit them per workload, then redeploy.

For TTS (Aura-2), use two GPUs — one for the generative model, one for the vocoder:

```python
# modal_deepgram/app.py
GPU = "L4:2"
CPU_COUNT = 8
MEMORY = 64 * 1024
```

For Deepgram's hardware minimums, see [Deployment Environments → Engine](https://developers.deepgram.com/docs/self-hosted-deployment-environments#engine). For Modal's GPU options, see [Modal: GPU](https://modal.com/docs/guide/gpu).

## Configure autoscaling

Modal automatically scales the number of Deepgram containers up and down based on per-container concurrency. 

See their [Scaling Out guide](https://modal.com/docs/guide/scale) and [Input Conccurrency guide](https://modal.com/docs/guide/concurrent-inputs) for the different parameters and their functionality. Note that not all available parameters are surfaced in `app.py`.

### Notes
> Deepgram recommends keeping at least one container active to ensure that lulls in traffic don't lead to queuing or 503s when scaling back up from zero. In Modal, set `min_containers = 1`.

> Web endpoints served with the `http_server` only accept a value for `target_inputs` and not `max_inputs`.

## Region Selection

To optimize network latency, most Deepgram deployments will set the `PROXY_REGION` AND `SERVER_REGION` and route traffic from clients in those regions to that deployment.

`PROXY_REGION` specifies the location of the Modal proxy that routes requests to containers. It can take one of four values: `us-east`, `us-west`, `eu-west`, `ap-south`.

`SERVER_REGION` specifies which region(s) the server containers can reside in. See the Modal [Region Selection doc](https://modal.com/docs/guide/region-selection) for more information.