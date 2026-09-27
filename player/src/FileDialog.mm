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

namespace {

// The accessory strip under a panel's name field. `slides` is the field every export has:
// which slides to take, opened with what the deck view has selected, or "all".
struct Accessory {
    NSView* box;
    CGFloat x = 10;
    void label(NSString* text, CGFloat w) {
        NSTextField* l = [NSTextField labelWithString:text];
        l.frame = NSMakeRect(x, 7, w, 18);
        l.alignment = NSTextAlignmentRight;
        [box addSubview:l];
        x += w + 6;
    }
    NSTextField* field(NSString* value, CGFloat w) {
        NSTextField* f = [[NSTextField alloc] initWithFrame:NSMakeRect(x, 4, w, 24)];
        f.stringValue = value;
        [box addSubview:f];
        x += w + 10;
        return f;
    }
};

NSTextField* slidesField(Accessory& a, const std::string& slidesDefault) {
    a.label(@"slides", 44);
    NSTextField* f = a.field(slidesDefault.empty() ? @"all" : [NSString stringWithUTF8String:slidesDefault.c_str()], 150);
    f.placeholderString = @"all, or 3-12, 20";
    return f;
}

std::string slidesValue(NSTextField* f) {
    std::string v = f.stringValue.UTF8String ?: "";
    return v == "all" ? std::string() : v;
}

}  // namespace

bool choosePdf(const std::string& dir, const std::string& name, const std::string& slidesDefault,
               PdfChoice* out) {
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
        Accessory a{[[NSView alloc] initWithFrame:NSMakeRect(0, 0, 420, 32)]};
        NSTextField* slides = slidesField(a, slidesDefault);
        panel.accessoryView = a.box;
        if ([panel runModal] != NSModalResponseOK) return false;
        NSURL* url = panel.URL;
        if (!url) return false;
        out->path = url.fileSystemRepresentation;
        out->slides = slidesValue(slides);
        return true;
    }
}

bool chooseVideo(const std::string& dir, const std::string& name, const std::string& slidesDefault,
                 VideoChoice* out) {
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
        // whole deck (or the deck view's selection) is prefilled, so the common case is to
        // type nothing.
        Accessory a{[[NSView alloc] initWithFrame:NSMakeRect(0, 0, 480, 32)]};
        NSTextField* slides = slidesField(a, slidesDefault);
        a.label(@"fps", 30);
        NSTextField* fpsField = a.field(@"30", 52);
        fpsField.alignment = NSTextAlignmentRight;
        // A caption line under the slides, from the transcripts (--transcribe): off unless
        // asked, since it makes the picture taller.
        NSButton* captionsBox = [NSButton checkboxWithTitle:@"captions" target:nil action:nil];
        captionsBox.frame = NSMakeRect(a.x, 6, 90, 20);
        captionsBox.state = NSControlStateValueOff;
        [a.box addSubview:captionsBox];
        panel.accessoryView = a.box;

        if ([panel runModal] != NSModalResponseOK) return false;
        NSURL* url = panel.URL;
        if (!url) return false;
        out->path = url.fileSystemRepresentation;
        out->slides = slidesValue(slides);
        out->fps = fpsField.doubleValue > 0 ? fpsField.doubleValue : 30.0;
        out->captions = captionsBox.state == NSControlStateValueOn;
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

bool chooseWebDir(const std::string& dir, const std::string& name, const std::string& slidesDefault,
                  WebChoice* out) {
    @autoreleasepool {
        NSSavePanel* panel = [NSSavePanel savePanel];
        panel.title = @"Export Web";
        panel.message = @"A folder for the site: the page, the slides, the narration and the player.";
        panel.prompt = @"Export";
        panel.canCreateDirectories = YES;
        panel.nameFieldStringValue = [NSString stringWithUTF8String:name.c_str()];
        if (!dir.empty()) {
            panel.directoryURL = [NSURL fileURLWithPath:[NSString stringWithUTF8String:dir.c_str()]];
        }
        Accessory a{[[NSView alloc] initWithFrame:NSMakeRect(0, 0, 420, 32)]};
        NSTextField* slides = slidesField(a, slidesDefault);
        panel.accessoryView = a.box;
        if ([panel runModal] != NSModalResponseOK) return false;
        NSURL* url = panel.URL;
        if (!url) return false;
        out->dir = url.fileSystemRepresentation;
        out->slides = slidesValue(slides);
        return true;
    }
}

bool trashIsAvailable() { return true; }

bool moveToTrash(const std::string& path) {
    @autoreleasepool {
        NSURL* url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:path.c_str()]];
        NSError* error = nil;
        const BOOL ok = [[NSFileManager defaultManager] trashItemAtURL:url resultingItemURL:nil error:&error];
        return ok == YES;
    }
}

}  // namespace refract
