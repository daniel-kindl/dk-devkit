# Load nvm inside the web-dev container.
#
# NVM_DIR is deliberately not the nvm default (~/.nvm): the isolated HOME keeps
# it under ~/.config so that the box home stays tidy.
#
# The devbox router runs commands through the box LOGIN shell (login_shell = 1
# in environments.d/web-dev.env), which is why this fragment is enough to make
# node and pnpm resolve for every routed command.
export NVM_DIR="$HOME/.config/nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
