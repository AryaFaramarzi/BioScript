from bioscript.symbol_table.symbol_table import SymbolTable
from bioscript.visitors.bs_base_visitor import BSBaseVisitor
from grammar.parsers.python.BSParser import BSParser
from shared.bs_exceptions import InvalidOperation
from shared.enums.instructions import Instruction


class TargetVisitor(BSBaseVisitor):

    def __init__(self, symbol_table: SymbolTable, name: str):
        self.name = name
        self.compiled = ""
        super().__init__(symbol_table)

    def add(self, code: str):
        self.compiled += code + self.nl

    def print_program(self):
        self.log.warning(self.compiled)

    def visitDetect(self, ctx: BSParser.DetectContext):
        output = "detect("
        module = self.check_identifier(ctx.IDENTIFIER(0).__str__())
        material = self.check_identifier(ctx.IDENTIFIER(1).__str__())
        output += "{}, {}, ".format(module, material)
        time = {}
        if ctx.timeIdentifier():
            time = self.visitTimeIdentifier(ctx.timeIdentifier())
            output += "{}".format(time['quantity'])
        else:
            time['quantity'] = 10.0
            time['unit'] = 's'
            output += "10.0"

        output += ");"

        is_simd = True if self.symbol_table.get_variable(material).size > 1 else False
        return {'operation': output, 'instruction': Instruction.DETECT,
                'args': {'input': material, 'module': module, 'time': time},
                'variable': self.symbol_table.get_variable(material),
                'size': self.symbol_table.get_variable(material).size, 'is_simd': is_simd}

    def visitSplit(self, ctx: BSParser.SplitContext):
        name = self.check_identifier(ctx.IDENTIFIER().__str__())
        # Split can never be a SIMD operation.
        return {"operation": "split({}, {});".format(name, ctx.INTEGER_LITERAL().__str__()),
                "instruction": Instruction.SPLIT, "size": int(ctx.INTEGER_LITERAL().__str__()),
                'args': {'input': name, "quantity": int(ctx.INTEGER_LITERAL().__str__())},
                'variable': self.symbol_table.get_variable(name), 'is_simd': False}

    def visitDispense(self, ctx: BSParser.DispenseContext):
        """
        Read the comment in visitVariableDeclaration() for further understanding of why
        is_simd = False and size = 1.  In short, the name of the variable in here
        is going to be a global variable and will always be of size = 1
        :param ctx:
        :return:
        """
        name = ctx.IDENTIFIER().__str__()
        return {'operation': "dispense({});".format(name),
                "instruction": Instruction.DISPENSE, 'size': 1,
                'args': {'input': name, 'quantity': 10.0}, 'variable': self.symbol_table.get_variable(name),
                'is_simd': False}

    def visitDispose(self, ctx: BSParser.DisposeContext):
        variable = self.symbol_table.get_variable(self.check_identifier(ctx.IDENTIFIER().__str__()))
        output = ""
        if variable.size > 1:
            """
            This is a SIMD operation
            """
            for x in range(0, variable.size):
                output += "dispose({}.at({});{}".format(variable.name, x, self.nl)
            output += "{} = nullptr;".format(variable.name)
        else:
            """
            This is not a SIMD operation
            """
            output += "dispose({});{}".format(variable.name, self.nl)
            output += "{} = nullptr;".format(variable.name)
        return output
        # return {'operation': "dispense({});".format(name),
        #         "instruction": Instruction.DISPOSE, 'size': self.symbol_table.get_variable(name).size,
        #         'args': {'input': name}, 'variable': self.symbol_table.get_variable(name), 'is_simd': is_simd}

    def visitMethodCall(self, ctx: BSParser.MethodCallContext):
        operation = "{}(".format(ctx.IDENTIFIER().__str__())
        arguments = ""
        method = self.symbol_table.functions[ctx.IDENTIFIER().__str__()]
        if ctx.expressionList():
            operation += "{}".format(self.visitExpressionList(ctx.expressionList()))
            arguments = "{}".format(self.visitExpressionList(ctx.expressionList()))
        operation += ");"
        is_simd = True if method.return_size > 1 else False
        return {'operation': operation, 'instruction': Instruction.METHOD,
                'args': {'args': arguments}, 'size': method.return_size, 'function': method, 'is_simd': is_simd}

    def visitMix(self, ctx: BSParser.MixContext):
        output = "mix("
        inputs = []
        time = {}
        test = set()
        for v in ctx.volumeIdentifier():
            var = self.visit(v)
            inputs.append(var)
            output += "{}, {}, ".format(self.check_identifier(var['variable'].name), var['quantity'])
            test.add(var['variable'].size)
        if len(test) != 1:
            raise InvalidOperation("Trying to run SIMD on unequal array sizes")
        if ctx.timeIdentifier():
            time = self.visitTimeIdentifier(ctx.timeIdentifier())
            output += time['quantity']
        else:
            output += "10.0"
            time['quantity'] = 10.0
            time['unit'] = 's'
        output += ");"
        is_simd = True if next(iter(test)) > 1 else False
        # This will get the first element of the set "test"
        return {'operation': output, 'instruction': Instruction.MIX,
                'args': {'input': inputs, 'time': time}, 'size': next(iter(test)), 'is_simd': is_simd}

    def visitExpression(self, ctx: BSParser.ExpressionContext):
        if ctx.primary():
            return self.visitPrimary(ctx.primary())
        else:
            exp1 = self.visitExpression(ctx.expression(0))
            exp2 = self.visitExpression(ctx.expression(1))
            if ctx.MULTIPLY():
                op = "*"
            elif ctx.DIVIDE():
                op = "/"
            elif ctx.ADDITION():
                op = "+"
            elif ctx.SUBTRACT():
                op = "-"
            elif ctx.AND():
                op = "&&"
            elif ctx.EQUALITY():
                op = "=="
            elif ctx.GT():
                op = ">"
            elif ctx.GTE:
                op = ">="
            elif ctx.LT():
                op = "<"
            elif ctx.LTE():
                op = "<="
            elif ctx.NOTEQUAL():
                op = "!="
            elif ctx.OR():
                op = "||"
            else:
                op = "=="

            if ctx.LBRACKET():
                """
                In this context, exp1 will *always* hold the variable name.
                So we can check to make sure that exp1 is the appropriate size,
                Given exp2 as the index. 
                """
                variable = self.symbol_table.get_variable(exp1)
                if int(exp2) > variable.size - 1 and int(exp2) >= 0:
                    raise InvalidOperation("Out of bounds index: {}[{}], where {} is of size: {}".format(
                        exp1, exp2, exp1, variable.size))
                output = "{}[{}]".format(exp1, exp2)
                self.log.info(output)
            else:
                output = "{}{}{}".format(exp1, op, exp2)

            return output