# Feedback Policy

Detailed feedback is permitted only for the `dev_feedback` split and only after a full agent batch is sealed, the agent Compose project is stopped, and the host transfers the submission. Builder Sol may correlate that feedback with host-side traces to make general improvements such as better tokenization, query construction, numeric parsing, prompt clarity, action repair, budgets, or recovery.

Feedback must not be converted into example-specific or statement-specific answer logic, prompt content, runtime files, build context, environment variables, or mounts. `dev_holdout` and `final_hidden` return aggregate scores only. Any set whose detailed outcomes influence implementation is a development set and cannot later be reported as hidden final evaluation.

