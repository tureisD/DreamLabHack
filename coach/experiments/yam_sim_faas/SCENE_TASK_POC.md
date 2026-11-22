# Robot-free new-task proof of concept

The existing click collector has fixed fruit goals. This proof of concept accepts a **new pick-and-place task as JSON**: its instruction, object shape/size/mass/color/start, target position/radius/color, and `place_on_target` success rule. The same code builds a fresh YAM MuJoCo scene, plans a grasp and placement, records three cameras and joint actions, checks physics, replays the exported 10 Hz actions, validates the LeRobot dataset with Dream, and places an unreviewed demo in the coach folder. A physical robot and Dream API call are not required for collection.

The supplied [red block to blue pad](scenes/red_block_to_blue_pad.json) and [yellow ball to green pad](scenes/yellow_ball_to_green_pad.json) tasks use different object shapes and instructions with no new task-specific Python.

## Try it

From `coach/`:

```powershell
uv sync --locked --extra sim
uv run --locked --extra sim python experiments/yam_sim_faas/scene_task.py --spec experiments/yam_sim_faas/scenes/red_block_to_blue_pad.json --seed 47 --preview scene.png
uv run --locked --extra sim python experiments/yam_sim_faas/scene_task.py --spec experiments/yam_sim_faas/scenes/red_block_to_blue_pad.json --seed 47 --collect --output yam_scene_task_demos
```

Or start `teach-task-coach serve`, create a local task with the exact instruction in the scene JSON, and use **Demos → Create a pick-and-place scene**. A successful demo appears for review; select **Keep** before including it in a FaaS dataset. Use fresh training seeds and reserve separate seeds for held-out evaluation.

The JSON is a deliberately small task language. It supports box, sphere, or cylinder objects within the YAM gripper's tested size and mass range, and a single marked tabletop target. If planning or the physical goal fails, no training episode is published. It does **not** generate arbitrary tasks such as towel folding, deformable manipulation, multi-object assembly, or a model policy for the new task. A validated scripted demo is data, not evidence that Dream-1 learned or that behavior transfers to a real robot.

## Where Blender fits

Blender can author geometry and materials, then export a mesh such as STL. The simulator still needs collision geometry, mass, contact settings, an object pose, and a measurable goal. This proof of concept uses MuJoCo primitives so those physical properties are explicit and reproducible; it works without Blender installed. The next extension is a Blender exporter that emits this scene JSON (and optionally a mesh), while MuJoCo remains the physics and verification engine. See [MuJoCo's MJCF modeling guide](https://mujoco.readthedocs.io/en/latest/modeling.html) and [Blender's STL export guide](https://docs.blender.org/manual/en/5.1/files/import_export/stl.html).
