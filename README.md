<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/dreamlabs-logo-dark.png">
  <img src="assets/dreamlabs-logo-light.png" alt="Dream Labs" width="520">
</picture>

<p>
  <a href="https://dreamlabs.ai"><strong>Blog Post</strong></a> |
  <a href="https://platform.dreamlabs.ai"><strong>DreamAPI</strong></a> |
  <a href="https://platform.dreamlabs.ai/api-documentation"><strong>Documentation</strong></a> |
  <a href="https://discord.gg/UAPxxH6tTg"><strong>Discord</strong></a>
</p>

</div>

## What is this library for

`dreamlabs` is the Python client for DreamAPI, which hosts **Dream-1**, the Dream Labs robot model. Dream-1 looks at
your robot's cameras and joint positions, reads the task you type, and answers with the next joint targets for the
arms, zero-shot, with no training on your robot.

It comes two ways:

- **`dreamcli`** runs your robot on our control loop: setup, cameras, arms and Live View, with no code to write.
- **`dream.DreamClient`** calls Dream-1 from your own control loop: you send observations, it returns actions.

## Quick Guide

Sign in at [platform.dreamlabs.ai](https://platform.dreamlabs.ai/api-keys) and create an API key. It is shown only
once, so keep it somewhere safe.

### dreamcli: our control loop

```bash
pip install dreamlabs
dreamcli setup       # arms and cameras
dreamcli robot up    # start the robot
```

Give it a task from [Live View](https://platform.dreamlabs.ai/live). For the full walkthrough, open
[Robot Setup](https://platform.dreamlabs.ai/setup).

### DreamClient: your own control loop

```bash
pip install dreamlabs-client
export DREAM_API_KEY=dl_live_...
```

```python
import dream

client = dream.DreamClient()
```

To run a model from your loop, see the [documentation](https://platform.dreamlabs.ai/api-documentation).

## Documentation

The [DreamAPI documentation](https://platform.dreamlabs.ai/api-documentation) covers everything beyond the quick
guide: getting started, calling Dream-1 from your own control loop with `dream.DreamClient`, showing your robot in
Live View, bringing a robot of your own, and fine-tuning Dream-1 on recordings of your robot.

## DreamCoach extension

This fork also includes [DreamCoach](coach/README.md), an experimental companion for teaching Dream-1 a task. It
guides a user from baseline failures through setup checks, demonstration review, Dream FaaS submission, and paired
evaluation of the resulting checkpoint. Robot motion, paid training, and checkpoint promotion remain under operator
control.

### Measured evaluation repair

We tested one completed apple-pickup fine-tune on fresh YAM simulator scenes without changing its weights or starting
another FaaS job. In eight matched scenes, a nine-request evaluation passed **7/8** and a twelve-request evaluation
passed **8/8**. In a separate, frozen twenty-scene confirmation, **14/19** valid trajectories met the two-second lift
rule by request nine and **19/19** did by request twelve; five first succeeded during request 10 or 11. One attempt
was invalid after a Dream episode restart and remains in the record. See the [protocol, run IDs, and reports](coach/experiments/yam_sim_faas/CLOSED_LOOP_REPAIR_STUDY.md), or open **Coach effect** in the app.

This shows why the coach checks execution and evaluation settings before recommending more demonstrations or another
fine-tune. It is a narrow simulator result. The [operator-study benchmark](coach/benchmark/README.md) is still
prospective; we have **not** measured reductions in operator time, demonstration count, or FaaS spend.

## License

Apache License 2.0 (`LICENSE`). Three of the vendored packages, `i2rt`, `pyroki` and `jaxls` under
`dream_library/vendor/`, keep their own MIT licenses, and the robot models and example assets that came from elsewhere
keep theirs, each in a `LICENSE` file in its own folder.
