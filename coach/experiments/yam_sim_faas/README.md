# Dream Labs YAM simulation FaaS test

Generated on 2026-11-21 from the Dream Labs `dream_library/examples/yam_mujoco` simulator in the local DreamLabHack checkout.

## Artifacts

- `expert-demos-10hz/`: two LeRobot v2.1 sessions of the repo's scripted YAM apple pickup. Both passed the simulator's lift, hold, and release check. Each contains 163 synchronized state/action rows and three camera videos at 10 Hz. Dream's local dataset validator accepted the combined dataset: 2 sessions, 2 episodes, 326 frames, 14 state dimensions, 14 action dimensions.
- `dream1-rollout-20hz/`: one separate rollout controlled by the live `dreamlabs/dream-1-beta` API in the same simulator. It recorded 65 rows, including setup, and executed 32 model action rows from one inference response. This is a baseline observation, not an expert demonstration; it was not included in the training upload.

## Live FaaS outcome

The coach imported and kept both scripted sessions, registered a simulated YAM embodiment, validated the frozen dataset, and uploaded it to Dream Labs as dataset `ds_c96e6b86bd8cbde9`. Dream's processing service returned `failed` with: "Processing failed because of an error on our side, not in your data. Retry it; if it fails again, contact us." Two SDK processing retries, including one on 2026-11-21 after the initial test, returned the same failure. The 1,000-step fine-tune was **not submitted**, so no training job or checkpoint exists from this test.

These simulated episodes verify data-format and upload mechanics. They do not establish improvement on a physical robot or provide a meaningful task-learning evaluation; the two expert episodes have the same starting scene.

No API credential is stored in these artifacts.

## Reproduce locally

The scripts use the adjacent Dream Labs `dream_library/examples/yam_mujoco` source. Install the coach environment plus `mujoco`, `pillow`, `av`, and `pyarrow`, then run from a scratch directory:

```bash
python path/to/coach/experiments/yam_sim_faas/record_yam_demos.py --output yam_sim_dataset_20hz
python path/to/coach/experiments/yam_sim_faas/resample_yam_demos.py --source yam_sim_dataset_20hz --output yam_sim_dataset_10hz
```

To make a separate model-controlled rollout, set `DREAM_API_KEY` in the process environment and run `record_dream_model_rollout.py --output yam_dream1_rollout`. The scripts never write the key into the dataset. The model rollout is not a successful expert demonstration and should not be mixed into the training data without review.
