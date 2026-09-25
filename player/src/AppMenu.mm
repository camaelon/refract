#include "AppMenu.h"

#import <Cocoa/Cocoa.h>

#include <memory>

namespace {

// The items, kept alive for the life of the program: the menu holds indices into this, and a
// menu outlives whatever built it.
std::vector<refract::MenuItem>& items() {
    static std::vector<refract::MenuItem> v;
    return v;
}

}  // namespace

// The target every item points at. AppKit wants an object with a selector; this turns the
// selector back into the entry it came from.
@interface RefractMenuTarget : NSObject
@end

@implementation RefractMenuTarget

- (void)fire:(id)sender {
    NSMenuItem* item = (NSMenuItem*)sender;
    const NSInteger index = item.tag;
    if (index < 0 || index >= (NSInteger)items().size()) return;
    if (items()[index].action) items()[index].action();
}

// Called by AppKit whenever the menu is about to be shown, which is exactly when the tick
// beside an item has to be right.
- (BOOL)validateMenuItem:(NSMenuItem*)item {
    const NSInteger index = item.tag;
    if (index >= 0 && index < (NSInteger)items().size() && items()[index].open) {
        item.state = items()[index].open() ? NSControlStateValueOn : NSControlStateValueOff;
    }
    return YES;
}

@end

namespace refract {

// Retained deliberately: the menu keeps an unowned reference to its target, and a target
// that went away would leave the items firing into nothing.
static RefractMenuTarget* menuTarget() {
    static RefractMenuTarget* target = [[RefractMenuTarget alloc] init];
    return target;
}

// Append to the shared item list and hand back an NSMenuItem per entry, tagged so the
// target can find its way back. One list for every menu: the tag is an index into it.
static std::vector<NSMenuItem*> makeItems(std::vector<MenuItem> menuItems) {
    std::vector<NSMenuItem*> made;
    for (auto& entry : menuItems) {
        items().push_back(std::move(entry));
        const size_t i = items().size() - 1;
        NSString* title = [NSString stringWithUTF8String:items()[i].title.c_str()];
        NSString* key = [NSString stringWithUTF8String:items()[i].key.c_str()];
        NSMenuItem* item = [[NSMenuItem alloc] initWithTitle:title
                                                      action:@selector(fire:)
                                               keyEquivalent:key];
        item.target = menuTarget();
        item.tag = (NSInteger)i;
        made.push_back(item);
    }
    return made;
}

void installFileMenu(std::vector<MenuItem> menuItems) {
    if (menuItems.empty()) return;
    NSMenu* bar = [NSApp mainMenu];
    if (!bar) return;

    NSMenu* fileMenu = nil;
    for (NSMenuItem* top in [bar itemArray]) {
        if ([[top title] isEqualToString:@"File"]) { fileMenu = [top submenu]; break; }
    }
    // Filled before it goes on the bar: a top-level menu that is empty when the bar first
    // sees it stays hidden, and items added to it afterwards do not bring it back.
    const bool fresh = fileMenu == nil;
    if (fresh) fileMenu = [[NSMenu alloc] initWithTitle:@"File"];
    for (NSMenuItem* item : makeItems(std::move(menuItems))) [fileMenu addItem:item];
    if (fresh) {
        // Straight after the application menu, where every Mac program keeps it.
        NSMenuItem* top = [[NSMenuItem alloc] initWithTitle:@"File" action:nil keyEquivalent:@""];
        [top setSubmenu:fileMenu];
        [bar insertItem:top atIndex:MIN(1, (NSInteger)[bar numberOfItems])];
    }
}

void installWindowMenu(std::vector<MenuItem> menuItems) {
    if (menuItems.empty()) return;

    NSMenu* bar = [NSApp mainMenu];
    if (!bar) return;

    // AppKit's own Window menu, which GLFW has already put Minimize and Zoom into. The
    // panels belong there rather than in a menu of their own: they are windows, and that is
    // where somebody looks for a window.
    NSMenu* windowMenu = [NSApp windowsMenu];
    if (!windowMenu) {
        for (NSMenuItem* top in [bar itemArray]) {
            if ([[top title] isEqualToString:@"Window"]) { windowMenu = [top submenu]; break; }
        }
    }
    if (!windowMenu) {
        NSMenuItem* top = [bar addItemWithTitle:@"Window" action:nil keyEquivalent:@""];
        windowMenu = [[NSMenu alloc] initWithTitle:@"Window"];
        [top setSubmenu:windowMenu];
    }

    // At the top, above Minimize and Zoom: opening a panel is what this menu is mostly for
    // in this program, and the standard entries are the afterthought here.
    NSInteger at = 0;
    for (NSMenuItem* item : makeItems(std::move(menuItems))) [windowMenu insertItem:item atIndex:at++];
    [windowMenu insertItem:[NSMenuItem separatorItem] atIndex:at];
}

}  // namespace refract
