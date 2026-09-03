// The navigator: an overlay over the live slide listing the whole deck, sections called
// out, with a preview of whatever row is highlighted. It is how you get somewhere else in
// the deck mid-talk — a question about an earlier section, a demo you want to skip back to
// — without paging through everything in between in front of the room.
#pragma once

#include "App.h"

#include "include/core/SkCanvas.h"

namespace refract {

// Everything the player draws on top of a rendered frame: the navigator, the pending
// "jump to slide N", the help card. It goes on the presenter window when there is one and
// on the slide window otherwise — none of it belongs on a projector if there is anywhere
// else to put it.
void drawOverlays(SkCanvas* canvas, App& app, int width, int height);

// Draw the navigator alone. Does nothing when app.navOpen is false.
void drawNavigator(SkCanvas* canvas, App& app, int width, int height);

// Move the highlight. `delta` is in rows; the cursor clamps at the ends rather than wrapping,
// because wrapping from the last slide to the title mid-talk is never what was meant.
void navMove(App& app, int delta);
// Move to the previous / next section heading.
void navMoveSection(App& app, int direction);

}  // namespace refract
