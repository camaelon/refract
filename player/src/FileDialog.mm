#include "FileDialog.h"

#import <Cocoa/Cocoa.h>

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
