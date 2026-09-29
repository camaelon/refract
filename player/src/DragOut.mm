#import <Cocoa/Cocoa.h>

#include "DragOut.h"

#define GLFW_EXPOSE_NATIVE_COCOA
#include <GLFW/glfw3.h>
#include <GLFW/glfw3native.h>

#include <filesystem>

namespace fs = std::filesystem;

// The source end of a drag. AppKit asks it what the drag is allowed to do, and holds it only
// weakly — so one instance is kept here for as long as the program runs rather than being
// made per drag and deallocated under a session that is still going.
@interface RcDragSource : NSObject <NSDraggingSource>
@end

@implementation RcDragSource
- (NSDragOperation)draggingSession:(NSDraggingSession*)session
    sourceOperationMaskForDraggingContext:(NSDraggingContext)context {
    (void)session;
    // Inside the app there is nothing to drop on; everywhere else it is a copy — the file
    // stays where it is and the receiver gets one of its own.
    return context == NSDraggingContextOutsideApplication ? NSDragOperationCopy : NSDragOperationNone;
}
@end

namespace {

// The event a drag can start from: the one being handled, when it is a mouse drag.
NSEvent* draggingEvent() {
    NSEvent* event = [NSApp currentEvent];
    if (!event) return nil;
    const NSEventType type = event.type;
    if (type != NSEventTypeLeftMouseDragged && type != NSEventTypeLeftMouseDown) return nil;
    return event;
}

// A label drawn as a small plate, for dragging something that has no picture of its own.
NSImage* plateFor(NSString* label) {
    NSFont* font = [NSFont systemFontOfSize:13 weight:NSFontWeightMedium];
    NSDictionary* attrs = @{NSFontAttributeName : font,
                            NSForegroundColorAttributeName : [NSColor labelColor]};
    NSSize text = [label sizeWithAttributes:attrs];
    const NSSize size = NSMakeSize(MIN(text.width + 28, 320), text.height + 16);
    NSImage* image = [[NSImage alloc] initWithSize:size];
    [image lockFocus];
    NSBezierPath* plate = [NSBezierPath bezierPathWithRoundedRect:NSMakeRect(0, 0, size.width, size.height)
                                                          xRadius:7 yRadius:7];
    [[NSColor.controlBackgroundColor colorWithAlphaComponent:0.95] setFill];
    [plate fill];
    [[NSColor.separatorColor colorWithAlphaComponent:0.8] setStroke];
    [plate stroke];
    [label drawInRect:NSMakeRect(14, 8, size.width - 28, text.height) withAttributes:attrs];
    [image unlockFocus];
    return image;
}

}  // namespace

namespace refract {

bool beginFileDrag(GLFWwindow* window, const std::string& file) {
    if (!window || file.empty()) return false;
    std::error_code ec;
    if (!fs::exists(file, ec)) return false;

    @autoreleasepool {
        NSWindow* ns = glfwGetCocoaWindow(window);
        NSView* view = ns.contentView;
        if (!view) return false;

        // The event being handled. A drag session can only start from a mouse event, and the
        // one in hand is the drag that asked for this.
        NSEvent* event = draggingEvent();
        if (!event) return false;

        NSString* path = [NSString stringWithUTF8String:file.c_str()];
        NSURL* url = [NSURL fileURLWithPath:path];
        NSImage* image = [[NSImage alloc] initWithContentsOfFile:path];
        if (!image) return false;

        // The picture under the pointer: a small copy of the slide, centred on the cursor.
        const CGFloat width = 260.0;
        const NSSize size = image.size;
        const CGFloat height = size.width > 0 ? width * size.height / size.width : width * 0.5625;
        const NSPoint at = [view convertPoint:event.locationInWindow fromView:nil];
        NSDraggingItem* item = [[NSDraggingItem alloc] initWithPasteboardWriter:url];
        [item setDraggingFrame:NSMakeRect(at.x - width * 0.5, at.y - height * 0.5, width, height)
                      contents:image];

        static RcDragSource* source = [[RcDragSource alloc] init];
        [view beginDraggingSessionWithItems:@[item] event:event source:source];
        return true;
    }
}

bool beginTextDrag(GLFWwindow* window, const std::string& text, const std::string& label) {
    if (!window || text.empty()) return false;
    @autoreleasepool {
        NSWindow* ns = glfwGetCocoaWindow(window);
        NSView* view = ns.contentView;
        if (!view) return false;
        NSEvent* event = draggingEvent();
        if (!event) return false;

        NSString* string = [NSString stringWithUTF8String:text.c_str()];
        if (!string) return false;
        NSImage* image = plateFor([NSString stringWithUTF8String:label.c_str()] ?: @"text");
        const NSPoint at = [view convertPoint:event.locationInWindow fromView:nil];
        NSDraggingItem* item = [[NSDraggingItem alloc] initWithPasteboardWriter:string];
        [item setDraggingFrame:NSMakeRect(at.x - image.size.width * 0.5, at.y - image.size.height * 0.5,
                                          image.size.width, image.size.height)
                      contents:image];

        static RcDragSource* source = [[RcDragSource alloc] init];
        [view beginDraggingSessionWithItems:@[item] event:event source:source];
        return true;
    }
}

}  // namespace refract
