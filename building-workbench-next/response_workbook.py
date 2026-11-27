"""Build a native Excel chart workbook from the exact exported observation intervals."""
from io import BytesIO
from math import isfinite

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.data_source import AxDataSource, StrRef
from openpyxl.styles import Alignment, Font, PatternFill


def workbook(payload):
    headers, rows = payload['headers'], payload['rows']
    groups, sources = payload['charts'], payload['sources']
    if not (isinstance(headers, list) and 1 < len(headers) <= 64 and
            isinstance(rows, list) and 0 < len(rows) <= 10080 and
            isinstance(groups, list) and 0 < len(groups) <= 12 and
            isinstance(sources, list) and len(sources) <= 64):
        raise ValueError('导出范围或曲线数量无效，请重新选择。')
    def write(ws, row_number, values):
        for col, val in enumerate(values, 1):
            cell = ws.cell(row_number, col)
            if isinstance(val, str) and len(val) <= 2048:
                cell.value = val
                cell.data_type = 's'
            elif val is None or type(val) in (float, int) and isfinite(val):
                cell.value = val
                if type(val) is float:
                    cell.number_format = '0.000'
            else:
                raise ValueError('导出数据包含无效单元格。')
    def table(ws, head, body):
        write(ws, 1, head)
        for row_number,row in enumerate(body,2):
            if not isinstance(row, list) or len(row) != len(head):
                raise ValueError('导出数据列数不一致。')
            write(ws, row_number, row)
        ws.freeze_panes = 'B2'
        ws.auto_filter.ref = ws.dimensions
        ws.sheet_view.showGridLines = False
        for cell in ws[1]:
            cell.font = Font(bold=True,color='FFFFFF')
            cell.fill = PatternFill('solid',fgColor='255B56')
            cell.alignment = Alignment(vertical='center',wrap_text=True)
            ws.column_dimensions[cell.column_letter].width = max(18,min(44,2*len(str(cell.value))+3))
        ws.row_dimensions[1].height = 32
    wb = Workbook()
    view = wb.active
    view.title = '曲线'
    data = wb.create_sheet('时序数据')
    meta = wb.create_sheet('测点与来源')
    table(data, headers, rows)
    table(meta, ['项目','内容'], sources)
    meta.column_dimensions['B'].width = 94
    view.sheet_view.showGridLines = False
    view['A1'] = '测点响应'
    view['A1'].font = Font(size=19,bold=True,color='204C46')
    view['A2'] = '修改「时序数据」中的数值，对应曲线会随之更新。'
    for i, group in enumerate(groups):
        chart = LineChart()
        chart.title = str(group['title'])[:100]
        chart.y_axis.title = str(group['unit'])[:32]
        chart.x_axis.title = '模拟时间（区间开始）'
        chart.x_axis.tickLblSkip = max(1,len(rows)//8)
        chart.x_axis.tickMarkSkip = chart.x_axis.tickLblSkip
        chart.width, chart.height = 27, 10
        chart.legend.position = 'b'
        cols = group['columns']
        if not isinstance(cols,list) or not cols or len(cols)>len(headers):
            raise ValueError('曲线未绑定数据列。')
        for n, col in enumerate(cols):
            if type(col) is not int or not 1 <= col < len(headers):
                raise ValueError('曲线数据列越界。')
            chart.add_data(Reference(data,min_col=col+1,min_row=1,max_row=len(rows)+1), titles_from_data=True)
            curve=chart.series[-1]
            curve.graphicalProperties.line.solidFill=('247568','B36138','477FA5','80699F','697C41','996A3D')[n%6]
            curve.graphicalProperties.line.width=21000
            curve.smooth=False
            curve.cat=AxDataSource(strRef=StrRef(f=str(Reference(data,min_col=1,min_row=2,max_row=len(rows)+1))))
        view.add_chart(chart,'A'+str(4+i*21))
    stream=BytesIO()
    wb.save(stream)
    return stream.getvalue()
