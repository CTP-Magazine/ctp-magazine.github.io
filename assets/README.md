# CTP Magazine — /assets

This is the magazine's own asset tree. Every CTP site keeps its own `/assets` with per-type/group subfolders — never a shared or central asset repo, never one flat folder.

## Structure

| Folder | What goes in it |
|--------|-----------------|
| `ctpeg/` | CTP Energy Glyphs. The folder name is `ctpeg` on every CTP site. |
| `hero/` | Hero banner images for the rotator, **1920×1080**. Only images from the safe pool (see below). |
| `branding/` | CTP Magazine logo and wordmark, CTP Energy logo. |
| `banners/` | Banner images, including the horizontal banner. |
| `ads/` | CTP Ads. |
| `ce-entities/` | CE Entities artwork, if used on the magazine. |

## Rules

- **Hero images are 1920×1080.** That is the file size in the repo. The page displays them at its default framing, not full 1920×1080 — file size and display framing are separate.
- **The horizontal banner is 2048×512 and never changes size.** Never resize, re-export, or crop it to 1920×1080. (Same locked rule as the CTP-EOS horizontal banner.)
- **Images in `hero/` come only from the safe pool** — NASA (public domain), ESO (CC BY 4.0 press images), and CC-BY journal figures. Fully credited, hand-picked, never auto-populated from RSS. Never put a commercial source's image in `/assets`. See the image-legalities rules in the repo.
- **All images are real files served from this tree.** No inlined base64 in `index.html` — that is what blew the CTP-EOS page up to 16.8 MB before the images were extracted. Keep `index.html` small and the images as files.
- **Attribution is recorded** for every image: source URL, licence, and credit, logged by the aggregator in `articles.json`.

## Adding an image

1. Check the licence covers it (safe pool only for hero images).
2. Resize to the right size first (1920×1080 for hero, 2048×512 for the horizontal banner).
3. Put it in the right subfolder, never loose in `/assets`.
4. Record its source, licence, and credit.
