# Flow diagrams

A flow diagram is plain HTML inside a ` ```flow ` fence. CSS grids place the boxes, and
`edges.js` draws the arrows after the fonts load. The diagram is drawn by hand, not laid out
automatically, so you decide where every box goes. That is what keeps it readable.

## Skeleton

```html
<div class="fig flow" data-edges='[
  {"from":"a","to":"b"},
  {"from":"b","to":"c","label":"HTTPS"},
  {"from":"zone1","to":"store","fx":"align","dash":true,"label":"reads","lp":"end"}
]'>
  <div class="zone" id="zone1">
    <div class="zlabel">Service · one container</div>
    <div class="row3">
      <div class="box primary" id="a"><b>API</b><span>entry point</span></div>
      <div class="box" id="b"><b>Worker</b><span>long-running</span></div>
      <div class="box child" id="c"><b>Child</b><span>isolated</span></div>
    </div>
  </div>
  <div class="row3" style="margin-top:40px">
    <div></div>
    <div class="box store" id="store"><i>store</i><b>MongoDB</b><span>durable state</span></div>
    <div></div>
  </div>
  <div class="bar">One sentence that states the key rule of the diagram.</div>
  <div class="legend"><span class="lg primary"></span>entry point <span class="lg plain"></span>process
    <span class="lg child"></span>isolated child <span class="lg ext"></span>outside the system
    <span class="lg dash"></span>optional</div>
</div>
```

The `data-edges` value is JSON inside a single-quoted attribute, so do not use a single quote in a label.
Every `id` must be unique in the whole document, so prefix ids for each diagram (`f1-api`, `f2-api`).

## Boxes

| Class | Look | Use it for |
| --- | --- | --- |
| `box` | white, solid black border | an ordinary component |
| `box primary` | filled green, white text | the entry point or the subject of the diagram. Use one or two at most. |
| `box ext` | dashed grey border | anything outside the system boundary |
| `box child` | orange border, orange subtitle | an isolated or attention-worthy part, such as a sandboxed child |
| `box slot` | green border | an in-process unit, such as a loop or a slot |
| `box slot opt` | dashed green border | an optional in-process unit |
| `box store` with `<i>store</i>` | small green "STORE" tag above the name | a database, bucket, or queue |

Inside a box, `<b>` holds the name and `<span>` holds a short subtitle of two to five words.
Long subtitles make tall boxes that misalign rows.

## Containers and layout

- `zone` is a dashed green rounded container with a light beige fill. `zone grey` is the neutral
  version for a boundary that is not the main subject. Put a `zlabel` inside for its small-caps label.
  Use `style="left:auto;right:12px"` on the `zlabel` when an arrow enters the zone at its top left.
- Rows: `row3`, `row4`, `row5` (equal columns). Grids that allow empty cells: `grid5`, `grid6`.
  Use `<div></div>` as an empty cell and `span2` for a box that covers two columns.
- `split` puts a main area beside a narrow `side` column (104px). `side` has a 29.3px top padding
  and 30px gaps, so its boxes line up with the rows of a `zone` that holds a `grid5`.
- Leave 30 to 46px of vertical space between rows that arrows cross (`style="margin-top:40px"`).
  An arrow label needs about 12px of that space.
- `bar` is the black pill caption under the diagram. `legend` explains the box types. Add a legend
  when the diagram uses three or more box types.

## Edge options

| Key | Effect |
| --- | --- |
| `from`, `to` | element ids. A zone can be an endpoint. |
| `dash` | dashed line, for optional, read-only, or configuration links |
| `both` | arrowheads at both ends |
| `label` | a small grey pill label |
| `lp` | label position: default is the middle, `"end"` is just above the target, `"side"` is beside the last vertical segment |
| `fx: "align"` | start a downward arrow at the x of the target, clamped inside the source. Use it when a wide zone fans out to a row of boxes, so each arrow is a straight line. |
| `mx: "gap"` | for a rightward arrow, put the vertical bend 16px before the target instead of halfway |

Routing is automatic and orthogonal:

- When the target is below the source, the arrow goes down, then across at the midpoint, then down.
- When the target is to the right, the arrow goes across, then up or down, then across. When the source center lies within the target's height, the arrow is a straight horizontal line.

Dashed edges are drawn first, so a solid edge that shares a segment stays visibly solid.

## Rules that keep a diagram clear

1. Lay out by layer: the actors at the top, the system in the middle, and the stores and external services at the bottom.
2. Do not let arrows run behind boxes. If an arrow must cross a row, move a box or use a side column.
3. When a diagram has more than about 12 arrows, draw only the structural ones. Then add a table after the
   diagram that lists every connection (From, To, What flows).
4. Keep labels to one to four words. Put detail in the table or the text.
5. Render the PDF, rasterize the page at 150 dpi or more, and look at it. Check for labels on arrowheads,
   arrows that leave the wrong box, and boxes of uneven height in one row.
