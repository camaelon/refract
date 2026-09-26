#include "FileDialog.h"

#import <Cocoa/Cocoa.h>

#include <algorithm>

namespace refract {

bool canChooseFiles() { return true; }

std::string chooseDeck() {
    @autoreleasepool {
        NSOpenPanel* panel = [NSOpenPanel openPanel];
        panel.canChooseDirectories = YES;
        panel.canChooseFiles = NO;
        panel.allowsMultipleSelection = NO;
        panel.title = @"Open deck";
        panel.message = @"Choose a deck — the folder with slides.md in it.";
        panel.prompt = @"Open";
        if ([panel runModal] != NSModalResponseOK) return {};
        NSURL* url = panel.URLs.firstObject;
        return url ? std::string(url.fileSystemRepresentation) : std::string();
    }
}

std::string choosePdf(const std::string& dir, const std::string& name) {
    @autoreleasepool {
        NSSavePanel* panel = [NSSavePanel savePanel];
        panel.title = @"Export PDF";
        panel.message = @"One page per slide, captured after each slide has animated in.";
        panel.prompt = @"Export";
        panel.nameFieldStringValue = [NSString stringWithUTF8String:name.c_str()];
        panel.allowedFileTypes = @[@"pdf"];
        panel.allowsOtherFileTypes = NO;
        if (!dir.empty()) {
            panel.directoryURL = [NSURL fileURLWithPath:[NSString stringWithUTF8String:dir.c_str()]];
        }
        if ([panel runModal] != NSModalResponseOK) return {};
        NSURL* url = panel.URL;
        return url ? std::string(url.fileSystemRepresentation) : std::string();
    }
}

bool chooseVideo(const std::string& dir, const std::string& name, int slideCount, VideoChoice* out) {
    @autoreleasepool {
        NSSavePanel* panel = [NSSavePanel savePanel];
        panel.title = @"Export Video";
        panel.message = @"The slides played with their narration, H.264 in an .mp4.";
        panel.prompt = @"Export";
        panel.nameFieldStringValue = [NSString stringWithUTF8String:name.c_str()];
        panel.allowedFileTypes = @[@"mp4"];
        panel.allowsOtherFileTypes = NO;
        if (!dir.empty()) {
            panel.directoryURL = [NSURL fileURLWithPath:[NSString stringWithUTF8String:dir.c_str()]];
        }

        // Under the name: which slides, and how many frames a second. Plain fields — the
        // whole deck is prefilled, so the common case is to type nothing.
        NSView* box = [[NSView alloc] initWithFrame:NSMakeRect(0, 0, 420, 32)];
        auto label = ^(NSString* text, CGFloat x, CGFloat w) {
            NSTextField* l = [NSTextField labelWithString:text];
            l.frame = NSMakeRect(x, 7, w, 18);
            l.alignment = NSTextAlignmentRight;
            [box addSubview:l];
        };
        auto field = ^NSTextField*(NSString* value, CGFloat x, CGFloat w) {
            NSTextField* f = [[NSTextField alloc] initWithFrame:NSMakeRect(x, 4, w, 24)];
            f.stringValue = value;
            f.alignment = NSTextAlignmentRight;
            [box addSubview:f];
            return f;
        };
        label(@"slides", 10, 50);
        NSTextField* fromField = field([NSString stringWithFormat:@"%d", 1], 66, 52);
        label(@"to", 122, 22);
        NSTextField* toField = field([NSString stringWithFormat:@"%d", slideCount], 148, 52);
        label(@"fps", 220, 40);
        NSTextField* fpsField = field(@"30", 266, 52);
        panel.accessoryView = box;

        if ([panel runModal] != NSModalResponseOK) return false;
        NSURL* url = panel.URL;
        if (!url) return false;
        out->path = url.fileSystemRepresentation;
        out->from = std::max(1, fromField.intValue);
        out->to = toField.intValue > 0 ? std::min(slideCount, toField.intValue) : slideCount;
        if (out->to < out->from) out->to = out->from;
        out->fps = fpsField.doubleValue > 0 ? fpsField.doubleValue : 30.0;
        return true;
    }
}

std::string chooseNewDeck() {
    @autoreleasepool {
        // A save panel rather than an open one: a new deck is a folder that does not exist
        // yet, and this is the panel that lets somebody name one.
        NSSavePanel* panel = [NSSavePanel savePanel];
        panel.title = @"New deck";
        panel.message = @"Where to put the new deck.";
        panel.prompt = @"Create";
        panel.nameFieldStringValue = @"talk";
        if ([panel runModal] != NSModalResponseOK) return {};
        NSURL* url = panel.URL;
        return url ? std::string(url.fileSystemRepresentation) : std::string();
    }
}

}  // namespace refract
