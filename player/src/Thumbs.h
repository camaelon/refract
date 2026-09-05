// Off-screen slide stills, for the presenter's "next up" pane and the navigator preview.
//
// A still is a full document render — same engine, same fonts, same shaders as playback —
// on its own raster surface, so it never touches the live document or the window surface.
//
// It is also expensive, and expensive in the worst possible place: a slide's opening
// transition animates *from* the previous slide, so a still has to step the document through
// real frames before it shows the slide rather than the one before it. On a heavy slide that
// is over a second — a second in which the deck would be frozen, at exactly the moment
// somebody scrolled the deck view or pressed a key.
//
// So stills are rendered on a worker thread. requestThumb() reads the file and queues the
// work; the worker renders it; collectThumbs() picks up whatever finished and puts it in the
// cache. Nothing blocks the frame. Callers ask for a slide long before they need it (the next
// slide is requested as soon as the current one loads), so it is usually there by the time it
// is looked at, and a card that is not yet drawn simply has no picture for a moment.
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

// Move whatever the worker finished into the cache. Call once per frame; it takes a lock
// and a move, and does no rendering.
void collectThumbs();

// True while there is work queued or waiting to be collected — for a caller that wants to
// keep redrawing until the pictures have arrived.
bool thumbsPending();

// Drop every cached and in-flight still. Called on reload, when the files may have changed;
// anything the worker is part-way through is discarded rather than delivered.
void clearThumbCache();

// Stop the worker and wait for it. Called once, at shutdown.
void stopThumbs();

}  // namespace refract
