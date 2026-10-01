// Loaded blocking in <head>, before the body paints: CSS keys the folded
// mobile filter drawer off html.js, so without JavaScript the filters stay
// visible, and with it they never flash open first.
document.documentElement.classList.add('js');
