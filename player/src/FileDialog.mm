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
