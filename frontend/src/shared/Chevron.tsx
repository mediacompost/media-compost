// ONE DROPDOWN CHEVRON. The five controls over the library grid drew their
// own: two named `var(--muted-2)` and three inherited their button's text
// colour, so one row of buttons carried three different greys and the
// brightest of them read as the most important control. The glyph, the
// colour and the size live here now.
//
// NOT every `expand_more` in the app: a TREE's disclosure is a different
// thing (it toggles between `expand_more` and `chevron_right`, and it
// belongs to the row it opens), and the image editor's menu bars draw
// theirs at 14 px and 70% white because they sit on a dark floating bar
// over a picture rather than on a panel.
import React from "react";
import { Icon } from "./Icon";

export function Chevron({ size = 17, style }: {
  /** Only where the control's own size really asks for it. */
  size?: number;
  style?: React.CSSProperties;
}) {
  return <Icon name="expand_more" size={size} color="var(--muted-2)" style={style} />;
}
