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
- `high_risk_text_region`

The first six are object scope labels, not assertions about sellability. The
last five identify visual context. `high_risk_text_region` records a visible
string only; it cannot become a product fact.

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
