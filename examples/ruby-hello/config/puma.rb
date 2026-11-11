# puma configuration for Runway: listen on the Unix socket in RUNWAY_SOCKET when it is set
# (umask 0117: only the owner and the web server group can connect), else on HOST:PORT.
# Never pass -b on the command line as well: it replaces every bind of this file.
socket = ENV["RUNWAY_SOCKET"].to_s
if socket.empty?
  bind "tcp://#{ENV.fetch('HOST', '127.0.0.1')}:#{ENV.fetch('PORT', '9292')}"
else
  bind "unix://#{socket}?umask=0117"
end

environment ENV.fetch("RACK_ENV", "production")
threads 1, 5
