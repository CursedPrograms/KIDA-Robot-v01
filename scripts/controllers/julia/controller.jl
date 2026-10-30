# A robot's controller in Julia (GLMakie). Everything about the robot is in ../robot.json, the same
# file the other languages read. Hold W A S D (Q E too, where it has them) to drive, Space to stop.
#
#   julia -e 'using Pkg; Pkg.add(["GLMakie", "HTTP", "JSON"])'
#   julia controller.jl [address]
using GLMakie
using HTTP
using JSON

const SPEC = JSON.parsefile(joinpath(@__DIR__, "..", "robot.json"))
host = isempty(ARGS) ? SPEC["host"] : ARGS[1]

function call(line)
    verb, rest = split(line, ' '; limit = 2)
    parts = split(rest, '|'; limit = 2)
    url = "http://$(host):$(SPEC["port"])$(parts[1])"
    try
        r = verb == "POST" ?
            HTTP.post(url, ["Content-Type" => "application/json"], length(parts) > 1 ? parts[2] : ""; readtimeout = 2, retry = false) :
            HTTP.get(url; readtimeout = 2, retry = false)
        return String(r.body)
    catch
        return nothing
    end
end

function tile(status, key)
    v = status
    for k in split(key, '.')
        (v isa AbstractDict && haskey(v, k)) || return "--"
        v = v[k]
    end
    string(v)
end

fig = Figure(size = (640, 400))
Label(fig[1, 1:4], SPEC["name"]; fontsize = 26, color = SPEC["accent"])
state = Observable("no answer")
Label(fig[2, 1:4], state)
for (i, b) in enumerate(SPEC["buttons"])
    btn = Button(fig[3 + (i - 1) ÷ 4, 1 + (i - 1) % 4]; label = b[1])
    on(_ -> @async(call(b[2])), btn.clicks)
end
row = 4 + (length(SPEC["buttons"]) - 1) ÷ 4
stopper = Button(fig[row, 1]; label = "STOP")
on(_ -> @async(call(SPEC["stop"])), stopper.clicks)
tiles = [Observable("$(t[1]): --") for t in SPEC["tiles"]]
for (i, t) in enumerate(tiles)
    Label(fig[row + 1 + (i - 1) ÷ 4, 1 + (i - 1) % 4], t)
end

const KEYS = Dict(Keyboard.w => "w", Keyboard.s => "s", Keyboard.a => "a", Keyboard.d => "d", Keyboard.q => "q", Keyboard.e => "e")
held = Ref{Union{Nothing,String}}(nothing)
on(events(fig).keyboardbutton) do e
    if e.key == Keyboard.space && e.action == Keyboard.press
        held[] = nothing
        @async call(SPEC["stop"])
    elseif haskey(KEYS, e.key) && haskey(SPEC["keys"], KEYS[e.key])
        if e.action == Keyboard.release
            held[] = nothing
            @async call(SPEC["stop"])
        elseif e.action == Keyboard.press
            held[] = SPEC["keys"][KEYS[e.key]]
        end
    end
end

@async while true
    held[] === nothing || call(held[])
    sleep(0.2)
end
@async while true
    body = call("GET " * SPEC["status"])
    state[] = body === nothing ? "no answer" : "connected"
    if body !== nothing
        try
            status = JSON.parse(body)
            for (i, t) in enumerate(SPEC["tiles"])
                tiles[i][] = "$(t[1]): $(tile(status, t[2]))$(t[3])"
            end
        catch
        end
    end
    sleep(0.5)
end

foreach(call, SPEC["connect"])
wait(display(fig))
