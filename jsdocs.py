"""
JSDocs v2.1.1
by Nick Fisher
https://github.com/spadgos/sublime-jsdocs
"""
import sublime_plugin
import re
import string


def read_line(view, point):
    if (point >= view.size()):
        return

    next_line = view.line(point)
    return view.substr(next_line)


def write(view, strng):
    view.run_command(
        'insert_snippet', {
            'contents': strng
        }
    )


def counter():
    count = 0
    while True:
        count += 1
        yield(count)


def escape(str):
    return string.replace(str, '$', '\$')


def is_numeric(val):
    try:
        float(val)
        return True
    except ValueError:
        return False


def getParser(view):
    scope = view.scope_name(view.sel()[0].end())
    viewSettings = view.settings()

    if re.search("source\\.php", scope):
        return JsdocsPHP(viewSettings)

    return JsdocsJavascript(viewSettings)


class JsdocsCommand(sublime_plugin.TextCommand):

    def run(self, edit, inline=False):
        v = self.view

        settings = v.settings()
        point = v.sel()[0].end()

        indentSpaces = max(0, settings.get("jsdocs_indentation_spaces", 1))
        prefix = "\n*" + (" " * indentSpaces)

        alignTags = settings.get("jsdocs_align_tags", 'deep')
        deepAlignTags = alignTags == 'deep'
        shallowAlignTags = alignTags in ('shallow', True)

        parser = getParser(v)
        parser.inline = inline

        # read the next line
        line = read_line(v, point + 1)
        out = None

        # if there is a line following this
        if line:
            if parser.isExistingComment(line):
                write(v, "\n *" + (" " * indentSpaces))
                return
            # match against a function declaration.
            out = parser.parse(line)

        # align the tags
        if out and (shallowAlignTags or deepAlignTags) and not inline:
            def outputWidth(str):
                # get the length of a string, after it is output as a snippet,
                # "${1:foo}" --> 3
                return len(string.replace(re.sub("[$][{]\\d+:([^}]+)[}]", "\\1", str), '\$', '$'))

            # count how many columns we have
            maxCols = 0
            # this is a 2d list of the widths per column per line
            widths = []
            #  skip the first one, since that's always the "description" line
            for line in out[1:]:
                widths.append(map(outputWidth, line.split(" ")))
                maxCols = max(maxCols, len(widths[-1]))

            #  i'm quite sure there's a better way to initialise a list to 0
            maxWidths = map(lambda x: 0, range(0, maxCols))

            if (shallowAlignTags):
                maxCols = 1

            for i in range(0, maxCols):
                for width in widths:
                    if (i < len(width)):
                        maxWidths[i] = max(maxWidths[i], width[i])

            for index, line in enumerate(out):
                if (index > 0):
                    newOut = []
                    for partIndex, part in enumerate(line.split(" ")):
                        newOut.append(part)
                        newOut.append(" " + (" " * (maxWidths[partIndex] - outputWidth(part))))
                    out[index] = "".join(newOut).strip()

        # fix all the tab stops so they're consecutive
        if out:
            tabIndex = counter()

            def swapTabs(m):
                return "%s%d%s" % (m.group(1), tabIndex.next(), m.group(2))

            for index, outputLine in enumerate(out):
                out[index] = re.sub("(\\$\\{)\\d+(:[^}]+\\})", swapTabs, outputLine)

        if inline:
            if out:
                write(v, " " + out[0] + " */")
            else:
                write(v, " $0 */")
        else:
            # write the first linebreak and star. this sets the indentation for the following snippets
            write(v, "\n *" + (" " * indentSpaces))
            if out:
                write(v, prefix.join(out) + "\n*/")
            else:
                write(v, "$0\n*/")


class JsdocsParser:

    def __init__(self, viewSettings):
        self.viewSettings = viewSettings
        self.setupSettings()

    def isExistingComment(self, line):
        return re.search('^\\s*\\*', line)

    def parse(self, line):
        out = self.parseFunction(line)  # (name, args)
        if (out):
            return self.formatFunction(*out)

        out = self.parseVar(line)
        if out:
            return self.formatVar(*out)

        return None

    def formatVar(self, name, val):
        out = []
        if not val or val == '':  # quick short circuit
            valType = "[type]"
        else:
            valType = self.guessTypeFromValue(val) or self.guessTypeFromName(name) or "[type]"

        if self.inline:
            out.append("@type %s${1:%s}%s ${1:[description]}" % (
                "{" if self.settings['curlyTypes'] else "",
                valType,
                "}" if self.settings['curlyTypes'] else ""
            ))
        else:
            out.append("${1:[%s description]}" % (escape(name)))
            out.append("@type %s${1:%s}%s" % (
                "{" if self.settings['curlyTypes'] else "",
                valType,
                "}" if self.settings['curlyTypes'] else ""
            ))

        return out

    def formatFunction(self, name, args):
        out = []

        out.append("${1:[%s description]}" % (name))

        self.addExtraTags(out)

        # if there are arguments, add a @param for each
        if (args):
            # remove comments inside the argument list.
            args = re.sub("/\*.*?\*/", '', args)
            for arg in self.parseArgs(args):
                out.append("@param %s${1:%s}%s %s ${1:[description]}" % (
                    "{" if self.settings['curlyTypes'] else "",
                    escape(arg[0] or self.guessTypeFromName(arg[1]) or "[type]"),
                    "}" if self.settings['curlyTypes'] else "",
                    escape(arg[1])
                ))

        retType = self.getFunctionReturnType(name)
        if retType is not None:
            out.append("@return %s${1:%s}%s" % (
                "{" if self.settings['curlyTypes'] else "",
                retType or "[type]",
                "}" if self.settings['curlyTypes'] else ""
            ))

        return out

    def getFunctionReturnType(self, name):
        """ returns None for no return type. False meaning unknown, or a string """
        name = re.sub("^[$_]", "", name)

        if re.match("[A-Z]", name):
            # no return, but should add a class
            return None

        if re.match('(?:set|add)[A-Z_]', name):
            # setter/mutator, no return
            return None

        if re.match('(?:is|has)[A-Z_]', name):  # functions starting with 'is' or 'has'
            return self.settings['bool']

        return False

    def parseArgs(self, args):
        """ an array of tuples, the first being the best guess at the type, the second being the name """
        out = []
        for arg in re.split('\s*,\s*', args):
            arg = arg.strip()
            out.append((self.getArgType(arg), self.getArgName(arg)))
        return out

    def getArgType(self, arg):
        return None

    def getArgName(self, arg):
        return arg

    def addExtraTags(self, out):
        extraTags = self.viewSettings.get('jsdocs_extra_tags', [])
        if (len(extraTags) > 0):
            out.extend(extraTags)

    def guessTypeFromName(self, name):
        name = re.sub("^[$_]", "", name)
        hungarian_map = self.viewSettings.get('jsdocs_notation_map', [])
        if len(hungarian_map):
            for rule in hungarian_map:
                print rule
                matched = False
                if 'prefix' in rule:
                    matched = re.match(rule['prefix'] + "[A-Z_]", name)
                elif 'regex' in rule:
                    matched = re.search(rule['regex'], name)

                if matched:

                    return self.settings[rule['type']] if rule['type'] in self.settings else rule['type']

        if (re.match("(?:is|has)[A-Z_]", name)):
            return self.settings['bool']

        if (re.match("^(?:cb|callback|done|next|fn)$", name)):
            return self.settings['function']

        return False


class JsdocsJavascript(JsdocsParser):
    def setupSettings(self):
        self.settings = {
            # curly brackets around the type information
            "curlyTypes": True,
            # technically, they can contain all sorts of unicode, but w/e
            "varIdentifier": '[a-zA-Z_$][a-zA-Z_$0-9]*',
            "fnIdentifier": '[a-zA-Z_$][a-zA-Z_$0-9]*',

            "bool": "Boolean",
            "function": "Function"
        }

    def parseFunction(self, line):
        res = re.search(
            #   fnName = function,  fnName : function
            '(?:(?P<name1>' + self.settings['varIdentifier'] + ')\s*[:=]\s*)?'
            + 'function'
            # function fnName
            + '(?:\s+(?P<name2>' + self.settings['fnIdentifier'] + '))?'
            # (arg1, arg2)
            + '\s*\((?P<args>.*)\)',
            line
        )
        if not res:
            return None

        # grab the name out of "name1 = function name2(foo)" preferring name1
        name = escape(res.group('name1') or res.group('name2') or '')
        args = res.group('args')

        return (name, args)

    def parseVar(self, line):
        res = re.search(
            #   var foo = blah,
            #       foo = blah;
            #   baz.foo = blah;
            #   baz = {
            #        foo : blah
            #   }

            '(?P<name>' + self.settings['varIdentifier'] + ')\s*[=:]\s*(?P<val>.*?)(?:[;,]|$)',
            line
        )
        if not res:
            return None

        return (res.group('name'), res.group('val').strip())

    def guessTypeFromValue(self, val):
        if is_numeric(val):
            return "Number"
        if val[0] == '"' or val[0] == "'":
            return "String"
        if val[0] == '[':
            return "Array"
        if val[0] == '{':
            return "Object"
        if val == 'true' or val == 'false':
            return 'Boolean'
        if re.match('RegExp\\b|\\/[^\\/]', val):
            return 'RegExp'
        if val[:4] == 'new ':
            res = re.search('new (' + self.settings['fnIdentifier'] + ')', val)
            return res and res.group(1) or None
        return None


class JsdocsPHP(JsdocsParser):
    def setupSettings(self):
        nameToken = '[a-zA-Z_\\x7f-\\xff][a-zA-Z0-9_\\x7f-\\xff]*'
        self.settings = {
            # curly brackets around the type information
            'curlyTypes': False,
            'varIdentifier': '[$]' + nameToken + '(?:->' + nameToken + ')*',
            'fnIdentifier': nameToken,
            "bool": "bool",
            "function": "function"
        }

    def parseFunction(self, line):
        res = re.search(
            'function\\s+'
            + '(?P<name>' + self.settings['fnIdentifier'] + ')'
            # function fnName
            # (arg1, arg2)
            + '\\s*\\((?P<args>.*)\)',
            line
        )
        if not res:
            return None

        return (res.group('name'), res.group('args'))

    def getArgType(self, arg):
        #  function add($x, $y = 1)
        res = re.search(
            '(?P<name>' + self.settings['varIdentifier'] + ")\\s*=\\s*(?P<val>.*)",
            arg
        )
        if res:
            return self.guessTypeFromValue(res.group('val'))

        #  function sum(Array $x)
        if re.search('\\S\\s', arg):
            return re.search("^(\\S+)", arg).group(1)
        else:
            return None

    def getArgName(self, arg):
        return re.search("(\\S+)(?:\\s*=.*)?$", arg).group(1)

    def parseVar(self, line):
        res = re.search(
            #   var $foo = blah,
            #       $foo = blah;
            #   $baz->foo = blah;
            #   $baz = array(
            #        'foo' => blah
            #   )

            '(?P<name>' + self.settings['varIdentifier'] + ')\\s*=>?\\s*(?P<val>.*?)(?:[;,]|$)',
            line
        )
        if res:
            return (res.group('name'), res.group('val').strip())

        res = re.search(
            '\\b(?:var|public|private|protected|static)\\s+(?P<name>' + self.settings['varIdentifier'] + ')',
            line
        )
        if res:
            return (res.group('name'), None)

        return None

    def guessTypeFromValue(self, val):
        if is_numeric(val):
            return "float" if '.' in val else "int"
        if val[0] == '"' or val[0] == "'":
            return "string"
        if val[:5] == 'array':
            return "Array"
        if val.lower() in ('true', 'false', 'filenotfound'):
            return 'bool'
        if val[:4] == 'new ':
            res = re.search('new (' + self.settings['fnIdentifier'] + ')', val)
            return res and res.group(1) or None
        return None

    def getFunctionReturnType(self, name):
        if (name[:2] == '__'):
            if name in ('__construct', '__set', '__unset', '__wakeup'):
                return None
            if name == '__sleep':
                return 'Array'
            if name == '__toString':
                return 'string'
            if name == '__isset':
                return 'bool'
        return JsdocsParser.getFunctionReturnType(self, name)


class JsdocsIndentCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        v = self.view
        currPos = v.sel()[0].begin()
        currLineRegion = v.line(currPos)
        currCol = currPos - currLineRegion.begin()  # which column we're currently in
        prevLine = v.substr(v.line(v.line(currPos).begin() - 1))
        spaces = self.getIndentSpaces(prevLine)
        toStar = len(re.search("^(\\s*\\*)", prevLine).group(1))
        toInsert = spaces - currCol + toStar
        if spaces is None or toInsert <= 0:
            v.run_command(
                'insert_snippet', {
                    'contents': "\t"
                }
            )
            return

        v.insert(edit, currPos, " " * toInsert)

    def getIndentSpaces(self, line):
        res = re.search("^\\s*\\*(?P<fromStar>\\s*@(?:param|property)\\s+\\S+\\s+\\S+\\s+)\\S", line) \
           or re.search("^\\s*\\*(?P<fromStar>\\s*@(?:returns?|define)\\s+\\S+\\s+)\\S", line) \
           or re.search("^\\s*\\*(?P<fromStar>\\s*@[a-z]+\\s+)\\S", line) \
           or re.search("^\\s*\\*(?P<fromStar>\\s*)", line)
        if res:
            return len(res.group('fromStar'))
        return None


class JsdocsJoinCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        v = self.view
        for sel in v.sel():
            for lineRegion in reversed(v.lines(sel)):
                v.replace(edit, v.find("[ \\t]*\\n[ \\t]*(\\*[ \\t]*)?", lineRegion.begin()), ' ')
