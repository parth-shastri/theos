# Source and license notices

The assistant uses the existing harness and renderer in this repository.
Their license remains in the root `LICENSE` file.

The health adapters use code by queryplanner from commit `d006624c150973a5637dbfb47ec0b4a6ff3ed613`.
`src/theos/services/health/normalize.py` and `src/theos/services/health/records.py` adapt its health normalization code and data models.
The original MIT notice is in [`src/theos/UPSTREAM-LICENSE`](../../src/theos/UPSTREAM-LICENSE).

The browser controls and visual tokens follow [ocr-checker commit e51dc10](https://github.com/parth-shastri/ocr-checker/tree/e51dc10935384935e55aa80026c7255e9df0d688).
The assistant uses its own HTML, JavaScript, and application icon.

The browser serves the Latin subset of Space Grotesk from `@fontsource-variable/space-grotesk` version `5.3.0`.
Its SIL Open Font License is in [`src/theos/transports/browser/static/SPACE-GROTESK-LICENSE`](../../src/theos/transports/browser/static/SPACE-GROTESK-LICENSE).
The application does not request the font from an external service.
