#include "Cursor.h"

#import <AppKit/AppKit.h>

namespace refract {

void setSystemCursorHidden(bool hidden) {
    static bool isHidden = false;
    if (hidden == isHidden) return;
    if (hidden) [NSCursor hide]; else [NSCursor unhide];
    isHidden = hidden;
}

}  // namespace refract
