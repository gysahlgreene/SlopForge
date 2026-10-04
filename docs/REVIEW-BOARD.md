# Local review board

Generate a static review page from the current project manifest:

```sh
slopforge --project ~/UnityProjects/MyGame review
open ~/UnityProjects/MyGame/slopforge-review.html
```

Choose another HTML path inside the project with `--output`, for example `--output ai/review/index.html`; asset links are calculated relative to that file. The board shows image candidates, model material previews and tracked outputs, prompts, seeds, model/workflow metadata, validation, status, and recipe parent/child/dependency relationships. Missing files stay visible. All displayed content is escaped, and manifest paths or board destinations that escape the project are rejected.

Candidate cards provide compare links and copyable CLI commands for approval/promotion, rejection, regeneration, and provenance inspection. Commands call the existing CLI and preserve validation and approval checks. Rejection records a timestamp and optional reason in the candidate manifest; it cannot reject the selected approved candidate. The board itself is static and local: it does not run commands or mutate approval state from the browser.
