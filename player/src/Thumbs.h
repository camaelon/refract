// Off-screen slide stills, for the presenter's "next up" pane and the navigator preview.
//
// A still is a full document render — same engine, same fonts, same shaders as playback —
// on its own raster surface, so it never touches the live document or the window surface.
//
// It is also expensive, and expensive in the worst possible place: a slide's opening
// transition animates *from* the previous slide, so a still has to step the document
// through real frames before it shows the slide rather than the one before it. Doing that
// in one go costs a second or more on a heavy slide, and the player is single-threaded —
// which is a frozen deck at exactly the moment the presenter pressed a key.
//
// So a still is built incrementally: requestThumb() starts a job, pumpThumbs() advances the
// jobs by a small time budget each frame, and thumbIfReady() returns the picture once it is
// finished. Callers ask for a slide long before they need it (the next slide is requested
// as soon as the current one loads), so by the time it is on screen it is usually done.
#pragma once

#include "include/core/SkImage.h"
#include "include/core/SkRefCnt.h"

#include <string>

namespace refract {

// The finished still for a playlist entry, or null while it is still being built.
// Requests the still if this is the first time it has been asked for.
sk_sp<SkImage> thumbIfReady(const std::string& entry, int width, int height);

// Start building a still without needing it yet.
void requestThumb(const std::string& entry, int width, int height);

// The finished still if it is already built, without queueing anything. A view showing many
// slides at once wants this: thumbIfReady() promotes what it is asked for to the front of the
// queue, and a grid asking for a screenful every frame would reshuffle the queue faster than
// any job could finish.
sk_sp<SkImage> thumbCached(const std::string& entry, int width, int height);

// Advance outstanding jobs by up to `budgetSeconds` of work. Call once per frame. A single
// document paint cannot be interrupted, so one paint can overrun the budget — the budget
// bounds how many paints happen per frame, not the length of the longest one.
void pumpThumbs(double budgetSeconds);

// Drop every cached and in-flight still. Called on reload, when the files may have changed.
void clearThumbCache();

}  // namespace refract
