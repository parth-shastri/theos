"""Redraw the uploaded framework with Excalidraw's traditional handwriting font."""

from __future__ import annotations

import base64
import html
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "architecture"
FONT = OUT / "fonts" / "Virgil.ttf"
INK = "#263447"
EDGE = "#53657b"
BLUE = "#e7f0ff"
GREEN = "#e5f5e8"
RED = "#ffe6e6"
PURPLE = "#f1eaff"
TEAL = "#e3f3f1"
YELLOW = "#fff3d9"


class Scene:
    def __init__(self, name, width, height):
        self.name, self.width, self.height = name, width, height
        self.elements = []
        self.fonts = {}

    def font(self, size):
        if size not in self.fonts:
            font = ImageFont.truetype(str(FONT), round(size))
            self.fonts[size] = font
        return self.fonts[size]

    def measure(self, value, size):
        lines = value.split("\n")
        return max(self.font(size).getlength(s) for s in lines), len(lines)*size*1.25

    def text(self, ident, x, y, value, size=24, color=INK, centered=False):
        w, h = self.measure(value, size)
        self.elements.append(dict(type="text", id=ident, x=x-w/2 if centered else x,
                                  y=y, width=w, height=h, text=value, fontSize=size,
                                  fontFamily=1, textAlign="center" if centered else "left",
                                  verticalAlign="top", autoResize=True, lineHeight=1.25,
                                  strokeColor=color, roughness=0))

    def shape(self, ident, kind, x, y, w, h, fill="transparent", stroke=EDGE, dashed=False):
        self.elements.append(dict(type=kind, id=ident, x=x, y=y, width=w, height=h,
                                  backgroundColor=fill, fillStyle="solid", strokeColor=stroke,
                                  strokeWidth=2, strokeStyle="dashed" if dashed else "solid",
                                  roughness=0.8, roundness={"type": 3} if kind=="rectangle" else None))

    def node(self, ident, kind, x, y, w, h, label, fill=BLUE, size=24):
        self.shape(ident, kind, x, y, w, h, fill)
        tw, th = self.measure(label, size)
        self.text(ident+"-label", x+w/2, y+(h-th)/2, label, size, centered=True)
        self.elements[-1].update(containerId=ident, verticalAlign="middle")
        self.elements[-2]["boundElements"] = [{"type": "text", "id": ident+"-label"}]

    def edge(self, ident, pts, head="arrow", dashed=False, color=EDGE):
        x, y = pts[0]
        self.elements.append(dict(type="arrow", id=ident, x=x, y=y,
                                  width=max(p[0] for p in pts)-min(p[0] for p in pts),
                                  height=max(p[1] for p in pts)-min(p[1] for p in pts),
                                  points=[[px-x, py-y] for px, py in pts],
                                  strokeColor=color, strokeWidth=2,
                                  strokeStyle="dashed" if dashed else "solid",
                                  endArrowhead=head, startArrowhead=None, roughness=0.6))

    def database(self, ident, x, y, label, width=130, height=100):
        self.shape(ident+"-body", "rectangle", x, y+15, width, height-30, TEAL)
        self.shape(ident+"-bottom", "ellipse", x, y+height-30, width, 30, TEAL)
        self.shape(ident+"-top", "ellipse", x, y, width, 30, TEAL)
        self.text(ident+"-caption", x+width/2, y+height+14, label, 20, centered=True)

    def files(self, ident, x, y):
        for i in range(3):
            self.shape(ident+str(i), "rectangle", x-i*8, y+i*8, 80, 95, "#ffffff")
        self.text(ident+"-caption", x+30, y+128, "Files + text", 20, centered=True)

    def title(self, label, subtitle):
        self.text("page-title", 55, 35, label, 38)
        self.text("page-subtitle", 55, 92, subtitle, 22, EDGE)

    def head_points(self, pts):
        x, y = pts[-1]
        px, py = pts[-2]
        a = math.atan2(y-py, x-px)
        return [(x-12*math.cos(a+s*.5), y-12*math.sin(a+s*.5)) for s in [-1, 1]]

    def save(self, cameras=None):
        full = []
        for i, raw in enumerate(self.elements):
            e = dict(angle=0, backgroundColor="transparent", fillStyle="solid",
                     strokeWidth=2, strokeStyle="solid", roughness=0.7, opacity=100,
                     groupIds=[], frameId=None, roundness=None, seed=(i+1)*193733,
                     version=1, versionNonce=(i+1)*3221, isDeleted=False,
                     boundElements=[], updated=1790985600000, link=None, locked=False)
            e.update(raw)
            if e["type"] == "text":
                e.setdefault("containerId", None)
                e["originalText"] = e["text"]
            elif e["type"] == "arrow":
                e.update(startBinding=None, endBinding=None, elbowed=False)
            full.append(e)
        native = dict(type="excalidraw", version=2, source="https://excalidraw.com",
                      elements=full, appState={"viewBackgroundColor": "#ffffff", "gridSize": None}, files={})
        (OUT/f"{self.name}.excalidraw").write_text(json.dumps(native, indent=2)+"\n")
        frame_w = max(self.width, self.height*4/3)
        frame_h = frame_w*.75
        start = {"type": "cameraUpdate", "x": -25, "y": -25, "width": frame_w+50, "height": frame_h+37.5}
        stream = [start] + full
        for c in cameras or []:
            stream.append(dict(type="cameraUpdate", **c))
        stream.append(start)
        (OUT/f"{self.name}.elements.json").write_text(json.dumps(stream, indent=2)+"\n")
        self.preview(full)

    def preview(self, elements):
        font_data = base64.b64encode(FONT.read_bytes()).decode()
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">',
               f'<style>@font-face{{font-family:DiagramHandwriting;src:url(data:font/ttf;base64,{font_data})}}text{{font-family:DiagramHandwriting,cursive;font-weight:400}}</style>',
               '<rect width="100%" height="100%" fill="white"/>']
        scale = 1.5
        image = Image.new("RGB", (round(self.width*scale), round(self.height*scale)), "white")
        draw = ImageDraw.Draw(image)
        scaled_fonts = {}
        for e in elements:
            x, y, w, h = e["x"], e["y"], e["width"], e["height"]
            stroke = e["strokeColor"]
            fill = e["backgroundColor"]
            style = ' stroke-dasharray="8 7"' if e["strokeStyle"] == "dashed" else ""
            box = (x*scale, y*scale, (x+w)*scale, (y+h)*scale)
            pil_fill = None if fill=="transparent" else fill
            if e["type"] == "rectangle":
                svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill if pil_fill else "none"}" stroke="{stroke}" stroke-width="2"{style}/>')
                draw.rounded_rectangle(box, radius=8*scale, fill=pil_fill, outline=stroke, width=3)
            elif e["type"] == "ellipse":
                svg.append(f'<ellipse cx="{x+w/2}" cy="{y+h/2}" rx="{w/2}" ry="{h/2}" fill="{fill if pil_fill else "none"}" stroke="{stroke}" stroke-width="2"/>')
                draw.ellipse(box, fill=pil_fill, outline=stroke, width=3)
            elif e["type"] == "diamond":
                pts=[(x+w/2,y),(x+w,y+h/2),(x+w/2,y+h),(x,y+h/2)]
                joined=" ".join(f"{a},{b}" for a,b in pts)
                svg.append(f'<polygon points="{joined}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
                draw.polygon([(a*scale,b*scale) for a,b in pts], fill=pil_fill, outline=stroke, width=3)
            elif e["type"] == "text":
                size=e["fontSize"]
                if size not in scaled_fonts:
                    scaled_fonts[size]=ImageFont.truetype(str(FONT),round(size*scale))
                for n, line in enumerate(e["text"].split("\n")):
                    line_x=x+(w-self.font(size).getlength(line))/2 if e["textAlign"]=="center" else x
                    line_y=y+n*size*1.25
                    svg.append(f'<text x="{line_x}" y="{line_y+size*.9}" fill="{stroke}" font-size="{size}">{html.escape(line)}</text>')
                    draw.text((line_x*scale,line_y*scale),line,font=scaled_fonts[size],fill=stroke,anchor="lt")
            elif e["type"] == "arrow":
                pts=[(x+a,y+b) for a,b in e["points"]]
                joined=" ".join(f"{a},{b}" for a,b in pts)
                svg.append(f'<polyline points="{joined}" fill="none" stroke="{stroke}" stroke-width="2" stroke-linejoin="round"{style}/>')
                for a,b in zip(pts,pts[1:]):
                    if e["strokeStyle"]=="dashed":
                        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
                        for k in range(0,math.ceil(length),15):
                            t,u=k/max(length,1),min(k+8,length)/max(length,1)
                            draw.line([((a[0]+dx*t)*scale,(a[1]+dy*t)*scale),((a[0]+dx*u)*scale,(a[1]+dy*u)*scale)],fill=stroke,width=3)
                    else:draw.line([(a[0]*scale,a[1]*scale),(b[0]*scale,b[1]*scale)],fill=stroke,width=3)
                if e["endArrowhead"]:
                    left,right=self.head_points(pts);head=[left,pts[-1],right]
                    joined=" ".join(f"{a},{b}" for a,b in head)
                    svg.append(f'<polyline points="{joined}" fill="none" stroke="{stroke}" stroke-width="2"/>')
                    draw.line([(a*scale,b*scale) for a,b in head],fill=stroke,width=3)
        (OUT/f"{self.name}.svg").write_text("\n".join(svg)+"\n</svg>\n")
        image.save(OUT/f"{self.name}.png")


def memory_blocks(d, y=930, prefix="memory"):
    for ident,x,title,body,fill in [
        ("procedural",130,"Procedural memory","Files + text\nProcedures and instructions\nSkills",PURPLE),
        ("semantic",560,"Semantic memory","Vector DB or files\nUser facts and preferences\nEnterprise documents",TEAL),
        ("episodic",990,"Episodic memory","SQL DB + vector store\nDated events across sessions\nUser memories across chats",TEAL),
    ]:
        d.shape(prefix+"-"+ident,"rectangle",x,y,330,190,fill)
        d.text(prefix+"-"+ident+"-title",x+165,y+18,title,25,centered=True)
        d.text(prefix+"-"+ident+"-body",x+22,y+68,body,19)
    d.files(prefix+"-files",250,y+280)
    d.database(prefix+"-facts-db",660,y+280,"Vector DB / files")
    d.database(prefix+"-episodes-db",1090,y+280,"SQL + vectors")
    for ident,x in [("files",290),("facts",725),("episodes",1155)]:
        d.edge(prefix+"-store-"+ident,[(x,y+280),(x,y+190)])
    d.edge(prefix+"-retrieval-bus",[(295,y-40),(1155,y-40)],head=None)
    for ident,x in [("procedure",295),("semantic",725),("episode",1155)]:
        d.edge(prefix+"-retrieve-"+ident,[(x,y),(x,y-40)],head=None)
    d.text(prefix+"-skills",150,y-78,"SKILL.md",20)
    d.text(prefix+"-rag-profile",590,y-78,"RAG + User.md",20)
    d.text(prefix+"-rag-sql",1000,y-78,"RAG + SQL / SQLite",20)


def consolidation(d, y=1400, prefix="extract"):
    d.node(prefix+"-trigger","diamond",1000,y,320,160,"Consolidate after\nconfigured N chats",YELLOW,22)
    d.edge(prefix+"-trigger-input",[(1220,y-140),(1330,y-140),(1330,y-40),(1160,y-40),(1160,y)])
    d.node(prefix+"-model","ellipse",960,y+200,340,120,"Summarize / extract\nGPT-6-Luna default",RED,24)
    d.node(prefix+"-prompt","rectangle",1320,y+213,120,90,"Extractor\nsystem\nprompt",PURPLE,20)
    d.edge(prefix+"-run",[(1160,y+160),(1160,y+180),(1130,y+180),(1130,y+200)])
    d.edge(prefix+"-prompt-model",[(1320,y+258),(1300,y+258)])
    d.edge(prefix+"-write-facts",[(960,y+260),(900,y+260),(900,y-140),(790,y-140)])
    d.text(prefix+"-distill",650,y+55,"Distill into facts",22)
    d.text(prefix+"-smaller",970,y+336,"Optional smaller extractor model",20,EDGE)


def ops_blocks(d, x=1515, y=145, prefix="ops"):
    d.shape(prefix+"-boundary","rectangle",x,y,820,1320)
    d.text(prefix+"-title",x+25,y+18,"LLMOps / traces and evaluations",28)
    d.node(prefix+"-trace","rectangle",x+35,y+105,270,170,"Trace\n1 trace per session\nLangfuse / LangSmith\nCustom exporter",BLUE,23)
    d.shape(prefix+"-eval-observe","rectangle",x+335,y+105,450,330,"#f8fafc")
    d.node(prefix+"-eval","rectangle",x+365,y+140,390,125,"Evals\nSimulation / LLM judge\nScores and checks",BLUE,24)
    d.node(prefix+"-observe","rectangle",x+365,y+295,390,110,"Observe\nLatency, health and usage",GREEN,24)
    d.node(prefix+"-diagnose","rectangle",x+375,y+535,360,150,"Diagnose\nFind the problem\nVisualize and aggregate",BLUE,25)
    d.node(prefix+"-gate","diamond",x+405,y+825,300,150,"Gate",YELLOW,28)
    d.node(prefix+"-release","rectangle",x+335,y+1095,450,170,"Release\nPrompt, tools, RAG settings\nModel and config changes\nPublish reviewed updates",GREEN,24)
    d.edge(prefix+"-trace-eval",[(x+305,y+190),(x+365,y+190)])
    d.edge(prefix+"-observe-diagnose",[(x+560,y+405),(x+560,y+470),(x+555,y+470),(x+555,y+535)])
    d.edge(prefix+"-diagnose-gate",[(x+555,y+685),(x+555,y+825)])
    d.edge(prefix+"-gate-release",[(x+555,y+975),(x+555,y+1095)])
    d.text(prefix+"-pass",x+577,y+1013,"pass",21)
    d.edge(prefix+"-fix-rerun",[(x+405,y+900),(x+155,y+900),(x+155,y+275)])
    d.text(prefix+"-fail",x+190,y+610,"Not passed:\nfix, rerun,\nre-evaluate",22)
    d.edge(prefix+"-feedback",[(x+705,y+900),(x+797,y+900),(x+797,y+202),(x+755,y+202)])
    d.text(prefix+"-feedback-label",x+610,y+730,"Feedback to evals",20)


def framework():
    d=Scene("theos-framework",2400,1800)
    d.title("Theos / Agent Harness", "A redraw of the uploaded framework · Default model: GPT-6-Luna")
    d.shape("harness-boundary","rectangle",50,145,1400,1630)
    d.text("harness-title",75,163,"Harness",30)
    d.shape("model-loop-boundary","rectangle",710,205,575,625,dashed=True)
    d.text("model-loop-title",730,225,"Model + tool loop",25)
    d.shape("working-boundary","rectangle",80,440,1340,390)
    d.text("working-title",105,455,"Working context and execution",25)
    d.node("tools","rectangle",850,280,400,130,"Tools\nSearch, weather, reminders, memory\nMeals, training, Gmail, sandbox\nFiles, speech, Zepto",PURPLE,20)
    d.node("user-prompt","rectangle",110,550,185,64,"User prompt",GREEN)
    d.node("recent-turns","rectangle",110,644,185,64,"Last N turns",BLUE)
    d.node("system-prompt","rectangle",110,738,185,64,"System prompt",BLUE,22)
    d.node("user-context","rectangle",400,500,280,64,"User context",TEAL)
    d.node("working-memory","rectangle",420,620,260,95,"Working memory\nContext building",BLUE,25)
    d.node("workflow","ellipse",725,605,290,125,"LLM-based workflow\nGPT-6-Luna",RED,24)
    d.node("end-condition","diamond",1060,580,210,170,"End loop\ncondition",YELLOW,24)
    d.node("final-response","rectangle",1300,633,110,86,"Final\nresponse",GREEN,22)
    d.edge("prompt-context",[(295,582),(355,582),(355,645),(420,645)])
    d.edge("history-context",[(295,676),(420,676)])
    d.edge("system-context",[(295,770),(385,770),(385,700),(420,700)])
    d.edge("profile-context",[(540,564),(540,620)])
    d.edge("context-model",[(680,667),(725,667)])
    d.edge("model-end",[(1015,667),(1060,667)])
    d.edge("end-answer",[(1270,667),(1300,667)])
    d.edge("continue-loop",[(1165,750),(1165,796),(696,796),(696,698),(680,698)])
    d.text("continue-label",845,764,"continue loop",20,EDGE)
    d.edge("tool-calls",[(805,608),(805,345),(850,345)])
    d.text("tool-calls-label",734,470,"Calls",20)
    d.edge("tool-results",[(1090,410),(1090,532),(945,532),(945,608)])
    d.text("tool-results-label",1110,462,"Results",20)
    memory_blocks(d)
    d.edge("memory-context",[(550,890),(550,715)])
    consolidation(d)
    ops_blocks(d)
    d.edge("harness-trace",[(1450,335),(1550,335)])
    d.text("trace-link-label",1457,299,"Trace",19)
    d.edge("release-harness",[(1850,1335),(1480,1335),(1480,790),(1450,790)])
    d.text("release-link-label",1550,1355,"Apply reviewed changes",21)
    return d


def memory():
    d=Scene("theos-memory",1500,1450)
    d.title("Theos / memory and consolidation", "Working memory above. Procedural, semantic and episodic memory below.")
    d.node("memory-working","rectangle",420,160,650,100,"Working memory / context building",BLUE,28)
    memory_blocks(d,y=390,prefix="focus-memory")
    d.edge("focus-to-working",[(550,350),(550,260)])
    consolidation(d,y=860,prefix="focus-extract")
    d.text("focus-memory-note",90,1370,"N chats is configurable. Extracted facts retain their source conversations.",23,EDGE)
    return d


def operations():
    d=Scene("theos-operations",940,1500)
    d.title("Theos / LLMOps", "Trace -> evaluate / observe -> diagnose -> gate -> release")
    ops_blocks(d,x=55,y=145,prefix="focus-ops")
    return d


def telegram():
    d=Scene("theos-telegram",1600,1200)
    d.title("Theos / Telegram integration", "An application transport around the shared harness · GPT-6-Luna / Responses")
    actors=[("telegram",70,"Telegram",GREEN),("runtime",470,"Theos runtime",BLUE),
            ("harness",870,"Agent harness",RED),("sqlite",1270,"SQLite",TEAL)]
    for name,x,label,fill in actors:
        d.node("actor-"+name,"rectangle",x,160,300,75,label,fill,26)
        d.edge("lifeline-"+name,[(x+150,235),(x+150,1050)],head=None,dashed=True,color="#a2adba")
    messages=[
        (220,620,290,"1. Message / callback"),
        (620,1420,390,"2. Authorize, deduplicate and persist"),
        (620,1020,490,"3. Resume / run turn"),
        (1020,1420,590,"4. Checkpoint tool call"),
        (1020,1420,690,"5. Persist tool result"),
        (1020,620,790,"6. Text, tools or approval wait"),
        (620,220,890,"7. Reply / approval buttons"),
        (220,620,990,"8. Owner callback -> validate"),
    ]
    for n,(start,end,y,label) in enumerate(messages):
        d.edge("message-"+str(n),[(start,y),(end,y)])
        tw,th=d.measure(label,22)
        d.shape("message-background-"+str(n),"rectangle",(start+end)/2-tw/2-8,y-40,tw+16,th+6,"#ffffff","#ffffff")
        d.elements[-1].update(strokeWidth=0,roughness=0,roundness=None)
        d.text("message-label-"+str(n),(start+end)/2,y-37,label,22,centered=True)
    d.shape("telegram-note","rectangle",470,1070,1100,86,YELLOW)
    d.text("telegram-note-text",493,1085,"SQLite holds pending updates, approvals and tool checkpoints.\nReminder delivery has durable states. Reply failures do not rerun turns.",22)
    return d


def tool_map():
    d=Scene("theos-tools",2450,2050)
    d.title("Theos / planned assistant tools", "Exact callable names · Optional connectors activate after configuration · GPT-6-Luna")
    d.node("tools-model","ellipse",140,155,490,125,"Theos model + tool loop\nGPT-6-Luna / Responses",RED,27)
    d.node("tools-registry","rectangle",900,155,710,125,"Tool registry + owner context\nTyped services / execution policies",PURPLE,27)
    d.edge("model-to-registry",[(630,218),(900,218)])
    d.text("tools-call-label",680,175,"tool calls",22)
    d.edge("tools-dispatch-bus",[(35,335),(1615,335)],head=None)
    d.edge("registry-dispatch",[(1255,280),(1255,335)],head=None)
    columns=[
        (60, [
            ("search", "Web search", "exa_search\nbrave_search", "Exa highlights / Brave titles, URLs and snippets", BLUE),
            ("weather", "Weather", "get_current_weather\nget_weather_forecast", "Open-Meteo conditions / 1-14 day forecast", BLUE),
            ("reminders", "Reminders", "schedule_reminder\nlist_reminders\ncancel_reminder", "SQLite jobs / local time + cron / Telegram delivery", GREEN),
            ("memory", "Personal memory", "save_memory\nsearch_memory\nget_all_memories\nget_memory\nupdate_memory\ndelete_memory", "Owner facts / semantic recall / correction / forgetting", TEAL),
            ("custom", "Custom tables + preferences", "create_custom_table\ndelete_custom_table\ncreate_query_template\nexecute_query_template\nlist_custom_tables_and_templates\nset_custom_instruction_override\ndelete_custom_instruction_override", "SQLite schemas + bound queries / style and units", TEAL),
        ]),
        (850, [
            (
                "workspace",
                "Task workspace",
                "run_command\nexecute_code\nwrite_file\nread_file\nlist_files\n"
                "upload_file\nsend_file_to_user\nview_image\nbrowser\nmanage_workspace",
                "Shell + Python / files / browser / images",
                PURPLE,
            ),
            (
                "files",
                "Durable Telegram files",
                "list_user_files\nrestore_user_file\ndelete_user_file",
                "R2 objects / sender ownership / restore to workspace",
                TEAL,
            ),
            (
                "skills",
                "Skills + browser",
                "load_skill\nload_skill_resource",
                "SKILL.md / repo exploration / browser",
                PURPLE,
            ),
            ("speech", "Speech delivery", "send_text_to_speech", "Kokoro text -> MP3 -> current Telegram chat", GREEN),
            ("health", "Google Health", "get_health_summary", "Read stored summaries / separate OAuth refresh job", TEAL),
            ("shopping", "Zepto shopping / MCP", "zepto_*  (discovered manifest)\nzepto_create_order\nzepto_create_online_payment_order\nzepto_create_upi_reserve_pay_order\nzepto_create_wallet_order", "Search / cart / address / history / confirm final order", GREEN),
        ]),
        (1640, [
            ("meals", "Meals + nutrition", "log_meal\nget_calorie_summary\nedit_meal\ndelete_meal\nset_calorie_goal\nget_meal_sync_status\nretry_meal_sync", "Estimated calories + macros / goals / Health export", TEAL),
            ("training", "Training", "set_training_program\nget_todays_training\nlog_training\nadvance_training_cycle\nget_training_history\nget_training_metrics\nupdate_training_metrics\ndelete_workout", "Rotating cycle / resistance + conditioning / metrics", TEAL),
            ("gmail", "Gmail", "gmail_search_messages\ngmail_get_message\ngmail_get_thread\ngmail_download_attachment\ngmail_list_drafts\ngmail_get_draft\ngmail_create_draft\ngmail_send_draft\ngmail_list_labels\ngmail_create_label\ngmail_modify_message_labels\ngmail_modify_thread_labels", "Private OAuth / drafts / custom labels / confirm send", GREEN),
            ("weekly", "Optional weekly workout compatibility", "log_workout\nget_last_workout\nset_workout_split\nget_todays_workout", "Weekly split / full exercise log / disabled by default", TEAL),
        ]),
    ]
    for x, groups in columns:
        y=390
        trunk=x-25
        last_center=y
        for ident,title,names,behavior,fill in groups:
            h=100+len(names.split("\n"))*27
            d.shape("cap-"+ident,"rectangle",x,y,730,h,fill)
            d.text("cap-"+ident+"-title",x+22,y+15,title,27)
            d.text("cap-"+ident+"-names",x+22,y+60,names,21)
            d.text("cap-"+ident+"-behavior",x+22,y+h-31,behavior,20,EDGE)
            last_center=y+h/2
            d.edge("cap-"+ident+"-dispatch",[(trunk,last_center),(x,last_center)])
            y+=h+32
        d.edge("tool-trunk-"+str(x),[(trunk,335),(trunk,last_center)],head=None)
    d.text("tools-note",60,1970,"Target capabilities, not implemented tools. See docs/tool-catalog.md for contracts, dependencies and delivery phases.",23,EDGE)
    return d


def main():
    for scene in [framework(),memory(),operations(),telegram(),tool_map()]:
        scene.save()
        print("Redrawn:",scene.name)


if __name__=="__main__":
    main()
