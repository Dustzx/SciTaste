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

No GitHub Pages deployment workflow is included yet. This prevents a repository
without Pages enabled from generating another failing Actions notification. Once
the owner selects the Pages source, deploy this directory as an immutable static
artifact and add the resulting public URL to the root README.

## Visual provenance

- `scitaste-mark.svg` is a repository-native vector mark representing candidate
  research paths, a taste decision, and one selected trajectory.
- `scitaste-lineage.webp` is a project-bound generated illustration created on
  2026-09-11 with the built-in image-generation path, then encoded locally as a
  metadata-free WebP. It depicts evidence converging into a taste decision and
  continuing through experiment, paper, and review.
- `scientific-taste-loop.svg` is a repository-native, text-safe diagram reducing
  the public Scientific Taste explanation to four readable nodes and one feedback
  loop.

The generated illustration is decorative; it is not a workflow result, evidence
artifact, product screenshot, or scientific claim.
