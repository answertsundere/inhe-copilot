# Product Media Annotation And Detector Feasibility

## Decision boundary

The current general-purpose visual providers do not meet the semantic object
qualification gate. This phase changes neither Product Media Observation v3 nor
any formal evidence path. It defines a small, reviewable annotation corpus for
a future detector feasibility experiment. Annotation boxes are not product
facts, and a trained detector would still need the existing panel, identity,
relationship, review, and high-risk gates.

## Reusable formats and tools

- [Label Studio pre-annotations](https://labelstud.io/guide/predictions.html)
  keep source references in `data` and model suggestions in `predictions`.
  This preserves OCR/provider provenance as editable suggestions rather than
  truth.
- [CVAT COCO support](https://docs.cvat.ai/docs/dataset_management/formats/format-coco/)
  and [MMDetection COCO dataset support](https://mmdetection.readthedocs.io/en/3.x/user_guides/train.html)
  make COCO the portable downstream interchange if a detector experiment is
  justified.
- [Ultralytics detection datasets](https://docs.ultralytics.com/datasets/detect)
  use normalized `class x_center y_center width height` boxes. It is compact
  for detector training but cannot encode object-to-label or panel relations,
  so it is not the authoring format.
- [Detectron2 custom datasets](https://detectron2.readthedocs.io/en/latest/tutorials/datasets.html)
  accepts COCO instances and supports additional per-instance fields through a
  custom mapper. It is suitable only after the pilot has stable labels and a
  separately defined evaluation split.
- [LayoutParser](https://layout-parser.github.io/) can reuse layout models and
  supports custom layout training, but its deep-learning path depends on a
  detector runtime. It is a later layout experiment, not an OCR replacement.
- [PaddleDetection](https://github.com/PaddlePaddle/PaddleDetection) supports
  COCO/VOC-style training but adds a separate Paddle/CUDA runtime surface. It
  is a candidate only if the pilot justifies another runtime.

Label Studio is recommended for the first internal pilot because the project
can import read-only OCR suggestions and attach Chinese instructions. CVAT is
an acceptable alternative where richer geometry tools are needed. Neither is
integrated into the customer-service application in this phase; exports require
an annotation-accessible image URL or a configured local storage path.

## Annotation schema

The authoring schema is product-independent. It applies to furniture, cups,
rackets, and other product families without using product names as labels.

### Region labels

- `product_overall`
- `packaging`
- `component`
- `accessory`
- `included_item`
- `display_prop`
- `label_text_region`
- `dimension_label_region`
- `mode_panel`
- `product_panel`
- `compliance_document_region`
- `high_risk_text_region`

The product, packaging, component, accessory, included-item, display-prop,
and compliance-document labels describe visual scope only, not sellability or
claim validity. The remaining labels identify visual context.
`high_risk_text_region` records a visible string only; it cannot become a
product fact.

### Relationships and attributes

Human annotation may record `panel_contains_object`, `label_describes_object`,
`dimension_measures_object`, `object_part_of_product`, and
`object_active_in_mode`. Candidate low-risk attributes are width, height,
depth, length, diameter, thickness, layer count, and compartment count.
Dimensions are always object- and panel-scoped:

- packaging dimensions remain packaging dimensions;
- component dimensions remain component dimensions;
- a mode-specific dimension remains tied to its mode;
- no annotation implies an overall-product dimension by itself.

The v4 authoring UI exposes these as a reviewer workflow instead of a flat
region list: first mark the mode or display panel, then the product instance
inside that panel, then the component or packaging, and finally the visible
dimension label. A dimension label must point to its measured object. When a
panel is present, that measured object must point to its panel; a mode-only
object can additionally point to its active mode. Reviewers also record only
the visible value/unit plus an attribute and scope choice. These fields are
external annotation metadata, not product facts.

The authoring palette is task-profiled rather than one static set of buttons.
`certificate_image` tasks use a compliance-document profile: reviewers can
mark the certification or test-document region, ordinary visible text, and
high-risk claim text. Packaging, components, and dimensions are deliberately
not offered in that profile. The document region only establishes what is
visible in the image; it never validates certification, safety, toxicity, or
any other product claim.

`load_capacity`, `non_toxic`, `food_grade`, `certification`, `child_safety`,
`anti_tip`, and `wall_mounting` are prohibited fact labels. If they appear in
an image, the only permitted label is `high_risk_text_region`.

## Pilot feasibility

The first corpus is a label-quality pilot, not a production training set. The
read-only feasibility script chooses the actual pilot size from media with an
accessible source reference, capped at 120. It prioritizes existing structured
media roles and scene tags: dimensions first, then packaging/mode/multi-panel
layout, then accessory and included-item scope. It never selects by product
name, SKU, file name, or customer text.

At this size, train/validation metrics mainly reveal label consistency, class
coverage, and obvious overfitting. They cannot establish robust cross-category
generalization. A detector experiment should begin only after two reviewers
agree on a calibration subset and error analysis shows category boundaries are
usable. The first candidate should be a low-capacity object detector trained
only for visual scopes; layout/OCR relationships remain separate review
annotations. COCO can support MMDetection or Detectron2-style evaluation later,
while YOLO is a possible detector-only derivative.

## Operational boundary

The application exports Label Studio tasks into `outputs/` in query-only mode.
It does not create observations, candidates, formal facts, review events, or
media-table updates. OCR is included only as a model prediction or task
metadata, and current object-provider output remains metadata. Importing human
labels, training a detector, and promoting any resulting observation require
separately approved future work.

For an external Label Studio instance, an application-relative media reference
is not sufficient: Label Studio resolves it against its own origin. The export
therefore requires a configured `--media-base-url` unless tasks are explicitly
materialized for Label Studio local storage. The original source reference stays
in task metadata for provenance. The media-serving endpoint permits the
configured Label Studio origin only, so browser-based review can load the
absolute media URL without broadening customer-facing media access.

## Small-batch Label Studio loop

Phase 0.4H.1 uses the existing schema to export a bounded twenty-image pilot.
The exporter reads original image bytes before task creation, calculates a
SHA-256 from those bytes, records dimensions and identity metadata, and can
materialize a local external-authoring copy outside the repository. Sampling is
balanced by durable media role and existing layout tags, never by product name,
SKU, image filename, or fixed coordinate.

The Label Studio task uses Label Studio's dynamic per-task label input with
Chinese region labels and five reviewer-only
relations: belongs-to, measured-object, visible-in-panel, active-in-mode, and
describes-object. The exported values map back to the canonical schema
relations; they are not customer-facing text and do not create evidence.
`high_risk_text_region` is the sole way to mark visible high-risk wording; it
does not carry a claim label. The post-export validator accepts only completed
human annotations, checks source hash/task continuity, rectangle bounds,
relation scope, duplicate regions, unknown labels, a missing measured object,
and missing panel scope when panels exist. It produces a rework queue rather
than trying to repair annotations.

Label Studio's documented JSON task format uses `data` for the image reference
and `predictions` for editable pre-annotations; its `Relations` tag represents
links between regions. Its [Visual Genome template](https://labelstud.io/templates/visual_genome)
documents dynamic `RectangleLabels` values sourced from task data. See also the
official [task import guide](https://labelstud.io/guide/tasks.html),
[pre-annotation guide](https://labelstud.io/guide/predictions.html), and
[Relations tag reference](https://labelstud.io/tags/relations). This is suitable
for a local pilot, not a production media-hosting design.

## Task-profiled authoring contract

Phase 0.4H.2 replaces the default broad authoring palette for new tasks with
four task profiles selected from durable task/media metadata, never product
titles, SKUs, image names, or coordinates:

| Profile | Reviewer labels | Scope boundary |
|---|---|---|
| `packaging_dimension` | packaging, visible text, dimension label, high-risk text | printed product artwork is not a product instance; every dimension remains packaging-scoped |
| `mode_dimension` | mode/product panels, current product instance, component, visible text, dimension label, high-risk text | packaging and props are unavailable; mode dimensions require a mode relation and cannot become overall dimensions |
| `product_specification` | product panel, current product instance, component, visible text, dimension label, high-risk text | material, colour, and layer copy remains visible text; age, safety, toxicity, load, certification, anti-tip, and wall-mounting copy is high-risk text |
| `compliance_document` | compliance document, visible text, high-risk text | a visible certificate or report is not proof that its claim is valid |

The previous `visual_layout` profile is retained only for historical manifest
validation. The exporter never chooses it for a new task. If current media
metadata cannot distinguish packaging or mode images, the exporter does not
inspect titles or guess; it uses the restricted product-specification profile
and records the metadata gap for later governance.

## Structured visual-description result

Completed annotations are compiled into a controlled, shadow-only description:

- product context: existing identity, human-aid title, visible variant/colour
  reference, and the source of product context;
- image: media role, controlled image scope, a short visible-only summary,
  visible text regions, and separately rejected high-risk text regions;
- panels: region ID, panel type, visible mode/state, and short panel summary;
- objects: region ID, object scope, parent panel/object relations, visible-only
  description, and actual-versus-printed representation state;
- dimensions: label region ID, visible value/unit, controlled attribute, measured
  object, packaging/product/component/mode scope, and review status.

Every descriptive item retains task UID, media asset ID, source-image SHA-256,
region ID, and bbox provenance. Missing provenance, an illegal profile label,
a printed product image marked as an actual product, a scope upgrade, or a
high-risk conclusion in free description produces a rework error. The result
is written only to the annotation validation report and remains outside formal
knowledge and Agent prompts.
