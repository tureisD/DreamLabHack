# Fresh held-out confirmation protocol

Predeclared before making any calls on seeds 905–908. The earlier 901–904 runs were used to diagnose a gripper-limit stop and an evaluation window that ended during the lift, so their longer reruns are exploratory.

- Scenes: deterministic YAM simulator seeds 905, 906, 907, 908; none are training scenes.
- Controllers: `dreamlabs/dream-1-beta` and `dream-1-ft:7820aef9-apple-varied24-500` on the same Dream account.
- Prompt and start: `pick up the apple`, `wrist-visible`, same simulator scene reset for each controller.
- Budget: 12 requests of up to 48 model action rows, executed at 20 Hz after 33 warm-up steps. A complete run has 609 simulator steps or 30.45 seconds. Wall-clock ceiling: 600 seconds.
- Recording: `--score-only` captures every action, joint state, and actual simulated apple height. Exact action replay must agree with saved joint states within 5 mm. Keep partial runs and count them as failures; do not quietly rerun them.
- Success: apple rises at least 8 cm over its settled height and stays at least that high for two continuous seconds. Report peak and held lift, first gripper-close time, replay error, and any partial run.
- Controller order: candidate then base on 905 and 907; base then candidate on 906 and 908.
- Interpretation: descriptive results out of four simulation scenes, with no claim about real robot performance or statistical significance.
