#include "App.h"

#include "rcplayer/Player.h"

namespace refract {

int App::current() const { return rcplayer::g.currentIndex; }

}  // namespace refract
