# SciTaste project page

This directory contains the dependency-free static project page. It intentionally
does not share code or state with the authenticated local Generation as Content
workspace under `src/scitaste/generative_ui/`.

## Local preview

From the repository root:

```bash
python3 -m http.server 8000 --directory site
```

Open <http://127.0.0.1:8000/>. The page performs no model, API, analytics, font,
or asset requests; outbound links activate only after a user follows them.

## Publishing boundary

The `Project page` workflow publishes only this directory to
<https://dustzx.github.io/SciTaste/>. It never uploads repository outputs,
manuscripts, credentials, or the local Generation as Content workspace.

GitHub requires one owner action before the first deployment:

1. Open **Settings → Pages** for the repository.
2. Under **Build and deployment**, set **Source** to **GitHub Actions**.
3. Open **Actions → Project page** and select **Run workflow** once.

After that, any push to `main` that changes `site/**` automatically publishes a
new immutable Pages artifact. Before the one-time setting is enabled, the
workflow reports a successful readiness notice and skips deployment instead of
creating a failing notification.

## Visual provenance

- `scitaste-mark.svg` is a repository-native vector mark representing candidate
  research paths, a taste decision, and one selected trajectory.
- `scitaste-lineage.webp` is a project-bound generated illustration created on
  2026-09-11 with the built-in image-generation path, then encoded locally as a
  metadata-free WebP. It depicts evidence converging into a taste decision and
  continuing through experiment, paper, and review.
- `scientific-taste-loop.svg` is an exact publication copy of the paper's
  repository-native Figure 1. It shows Taste Case formation, the Knowledge/Taste
  boundary, next-action control, bounded work, and deterministic state admission.

The generated illustration is decorative; it is not a workflow result, evidence
artifact, product screenshot, or scientific claim.
