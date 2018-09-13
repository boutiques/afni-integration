"""
Functions for generating boutiques descriptors from AFNI help
"""
import argparse
from itertools import chain
import json
from pathlib import Path
import re
import boutiques.creator as bc
import numpy as np

ALPHANUM = re.compile("[\W_]+")
CLEANARG = re.compile("[^0-9_a-zA-Z\-]")
FINDARGS = re.compile("ARGS=\((.*) ?\)")
FINDHELP = re.compile("\s*(-[\s\w]*)[=:}][\s\S]")
IGNOREOR = re.compile("^\s*\*\s*OR\s*\*")
PARTJSON = re.compile("(_part\d+)$")
WHISPACE = re.compile('\s+')


def gen_outdir(outdir):
    """
    Coerces `outdir` to `pathlib.Path` and creates it, if it doesn't exist

    Parameters
    ----------
    outdir : str
        Path to desired output directory

    Returns
    -------
    outdir : pathlib.Path
        Path to desired output directory
    """
    outdir = Path(outdir).resolve()
    outdir.mkdir(exist_ok=True)

    return outdir


def get_complete_args(fname):
    """
    Grabs parsed arguments for a given AFNI command in `fname`

    The file at `fname` should be a parsed AFNI command file generated by
    running `apsearch -update_all_afni_help`

    Parameters
    ----------
    fname : str
        Path to "XXXXX.complete.bash" file describing parsed AFNI command

    Returns
    -------
    args : list of str
        Putative arguments for command defined by `fname`
    """
    fpath = Path(fname).expanduser()
    if not fpath.exists():
        raise FileNotFoundError('{} does not seem to exist?'.format(fname))

    args = FINDARGS.findall(fpath.read_text(errors='ignore'))
    try:
        args = args[0].strip().replace('\'', '').split(' ')
    except IndexError:
        raise IndexError('Unable to find arguments for {}'.format(fname))

    args = list(set([CLEANARG.sub('', a) for a in args]))
    return args


def get_usage_string(fname):
    """
    Attempt to read usage string for a given AFNI command in `fname`

    The file at `fname` should be a full AFNI help text file generated by
    running `apsearch -update_all_afni_help`

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command

    Returns
    -------
    usage : str
        Line detailing usage for command in `fname`
    """
    text_list = fname.read_text(errors='ignore').splitlines()
    usage_text = [val for val in text_list if
                  val.lower().strip().startswith('usage')]
    if usage_text:
        return usage_text[0]
    else:
        return None


def get_usage_params(fname):
    """
    Gets positional parameters for AFNI command in `fname` from usage string

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command

    Returns
    -------
    positional : list of str
        List of putative positional arguments for command in `fname`
    """
    usage_text = get_usage_string(Path(fname))
    if usage_text:
        text_with_bracket_args = re.sub('\[[^\[\]]*\]', '', usage_text)
        text_without_bracket_args = text_with_bracket_args.split(':')[1]
        text_with_spaces = re.sub(
            '\s+',
            ' ',
            text_without_bracket_args).strip()
        args = []
        ignore = False
        for a in text_with_spaces.split(' ')[1:]:
            if a.startswith('~'):
                continue
            if a.startswith('-'):
                ignore = True
                continue
            if ignore:
                ignore = False
                continue
            args += [a]
    else:
        args = []
    return args


def get_help_fname(help_dir, cmd):
    """
    Gets most recently generated helptext for AFNI `cmd` in `help_dir`

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    cmd : str
        AFNI command to grab help file for

    Returns
    -------
    help_fname : str
        Path to help file
    """
    help_dir = Path(help_dir).resolve()
    help_fnames = sorted(help_dir.glob(cmd + '.????_??_??-??_??_??.help'))
    try:
        return help_fnames[-1]
    except IndexError:
        raise FileNotFoundError('Cannot find any valid help files for {} in {}'
                                .format(cmd, help_dir.as_posix()))


def _get_basic_help(fname, putative=None):
    """
    Gets command arguments and line number in help text for command in `fname`

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command
    putative : list of str
        List of putative argument for a given AFNI command

    Returns
    -------
    params : list of dict
        Where each entry has keys ['param', 'line_start', 'length'] detailing
        the parameter name ('param'), the first line of its description in
        `helptext` ('line_start'), and putative length of its description in
        line numbers
    helptext : str
        Full helptext of tool in `fname`
    """
    helptext = Path(fname).read_text(errors='ignore').splitlines()
    params = []
    # grab parameters and line starts
    currchar = 0
    for n, f in enumerate(helptext):
        if FINDHELP.match(f) is None:
            currchar += len(f) + 1
            continue
        param = FINDHELP.findall(f)[0].strip().split(' ')[0]
        if ALPHANUM.sub('', param) == '':
            currchar += len(f) + 1
            continue
        begin = currchar + f.find(param)
        params += [dict(param=param, line_start=n, length=None,
                        param_range=[begin, begin + len(param)])]
        currchar += len(f) + 1

    # compare to list of putative arguments
    if putative is not None:
        missing = list(set(putative) - set([p.get('param') for p in params]))
        for miss in missing:
            if ALPHANUM.sub('', miss) == '':
                continue
            currchar = 0
            for n, f in enumerate(helptext):
                starts = [p.get('line_start') for p in params]
                if f.strip().startswith(miss) and n not in starts:
                    begin = currchar + f.find(miss)
                    params += [dict(param=miss, line_start=n, length=None,
                                    param_range=[begin, begin + len(miss)])]
                currchar += len(f) + 1

    # sort by line start in preparation for calculating lengths of descriptions
    params = sorted(params, key=lambda x: x.get('line_start'))

    # update potential lengths of help text
    for n, f in enumerate(params[:-1]):
        params[n]['length'] = (params[n + 1].get('line_start') -
                               f.get('line_start'))

    return params, helptext


def get_full_help(fname, putative=None):
    """
    Gets arguments and argument descriptions for command help text in `fname`

    Parameters
    ----------
    fname : str
        Path to full helptext for a given AFNI command
    putative : list of str
        List of putative argument for a given AFNI command

    Returns
    -------
    params : list of dict
        Where each entry has keys ['param', 'line_start', 'length',
        'help', 'param_range', 'help_range'] detailing the parameter name
        ('param'), the first line of its description in `helptext`
        ('line_start'), the putative length of its description in line numbers,
        an attempt at parsing that description from `helptext` ('help'), the
        character slice for the parameter string ('param_range'), and the
        character slice for the putative help string ('help_range')
    helptext : str
        Full helptext of tool in `fname`
    """
    params, helptext = _get_basic_help(fname, putative=putative)
    fullhelp = '\n'.join(helptext)
    # iterate through parameters and get approximate description for each
    for param in params:
        ls, ln = param.get('line_start'), param.get('length')
        if ln is None:
            ln = len(helptext) + 1 - ls
        lines = helptext[ls:ls + ln]
        for n, f in enumerate(lines):
            stripped = f.lstrip()
            match = FINDHELP.match(stripped)
            if match is not None:
                lines[n] = stripped[match.end():]
                break
        param_descrip = '\n'.join(lines).rstrip()
        param['help'] = param_descrip
        ind = fullhelp.find(param_descrip)
        if ind == -1:
            ind = param['param_range'][0]
        param['help_range'] = [ind, ind + len(param_descrip)]

    return params, helptext


def gen_help_jsons(help_dir, outdir='to_boutify', split_char=5000,
                   verbose=True):
    """
    Generates individual JSON files for each AFNI command in `help_dir`

    Output JSON files contain:
        1. Entire helptext for command, split into lines
        2. List of putative parameters for command, including starting line in
           help text and length of description

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    outdir : str
        Path to where output JSON files should be saved
    split_char : int, optional
        Approximate number of characters at which to split help text
    verbose : bool, optional
        Whether to print status messages. Default: True

    Returns
    -------
    jsons : list of str
        Paths to saved JSON files
    """

    def get_ranges(param):
        """ Selects only 'help_range' and 'param_range' keys from `param` """
        return dict(param_range=param['param_range'],
                    help_range=param['help_range'])

    outdir = gen_outdir(outdir)
    help_dir = Path(help_dir).resolve()

    jsons = []
    # iterate through tools and get help information
    for tool in help_dir.glob('*.complete.bash'):
        tool_name = tool.name.replace('.complete.bash', '')
        if verbose:
            print('Generating JSON for {}.'.format(tool_name))
        # get parameter information + helptext
        params, helptext = get_full_help(get_help_fname(help_dir, tool_name),
                                         putative=get_complete_args(tool))
        # we can't have periods in our filenames!
        tool_name = tool_name.replace('.', '_')
        # we only need the param_range and help_range keys for each parameter
        params = [get_ranges(p) for p in params]
        # only save out one JSON if that's all we need
        if len('\n'.join(helptext)) < split_char:
            fname = outdir.joinpath('{}.json'.format(tool_name))
            with fname.open('w') as dest:
                json.dump(dict(helptext=helptext, params=params), dest)
            continue

        # if len(helptext) is larger than `split_char`, split it into chunks!
        split_jsons = split_help(params, helptext, split_char)

        # save out each parameter list / helptext chunk separately
        temp = '{}_part{}.json'
        for n, part in enumerate(split_jsons):
            # get previous / next filenames for multi-part helps
            part['previous'] = fname if n > 0 else ''
            fname = temp.format(tool_name, n + 1)
            jsons.append(outdir.joinpath(fname))
            part['next'] = temp.format(tool_name, n + 2) if n < len(split_jsons) -1 else ''  # noqa
            # save out chunk to CMD_partXX.json file
            with jsons[-1].open('w') as dest:
                json.dump(part, dest)

    # write `all_programs` file so we know what's in the directory
    with outdir.joinpath('all_programs').open('w') as dest:
        json.dump([p.name for p in jsons], dest)

    return jsons


def split_help(params, helptext, split_char=5000, pad=1000):
    """
    Splits `params` and `helptext` into chunks of approximately `split_char`

    Parameters
    ----------
    params : list of dict
        Where each entry has keys ['param', 'line_start', 'length',
        'help', 'param_range', 'help_range'] detailing the parameter name
        ('param'), the first line of its description in `helptext`
        ('line_start'), the putative length of its description in line numbers,
        an attempt at parsing that description from `helptext` ('help'), the
        character slice for the parameter string ('param_range'), and the
        character slice for the putative help string ('help_range')
    helptext : list of str
        Full helptext of tool in `fname`, broken at lines
    split_char : int, optional
        Approximate size of character chunks to split helptext into
    pad : int, optional
        Padding around `split_char`

    Returns
    -------
    split : list of dict
        List of split-ified `params` and `helptext` such that each `helptext`
        is approximately `split_char` in length
    """
    def fix_param(param, subtract):
        """ Reset parameter ranges in `param` based on `subtract` """
        param['param_range'] = [pp - subtract for pp in param['param_range']]
        param['help_range'] = [pp - subtract for pp in param['help_range']]
        return param

    params = [f.copy() for f in params]
    helptext = '\n'.join(helptext)
    helplen = len(helptext) + 1

    # find where to split parameters based on length of helptext
    curr_char = last_char = 0
    param_split = []
    for n, p in enumerate(params):
        curr_char = p['help_range'][-1] - last_char
        if curr_char > split_char:
            param_split += [n]
            curr_char = 0
            last_char = p['help_range'][-1]
    param_split = np.split(params, param_split)

    # clip helptext based on splits and reset param ranges so characters align
    split = [0] + [f[0]['param_range'][0] for f in param_split[1:]] + [helplen]
    save_as_jsons = []
    for n, (start, end) in enumerate(zip(split, split[1:])):
        if start > pad:
            start -= pad
        curr_help = helptext[start:end + pad].splitlines()
        curr_params = [fix_param(p, start) for p in param_split[n]]
        save_as_jsons.append(dict(helptext=curr_help, params=curr_params))

    return save_as_jsons


def gen_boutique_descriptors(help_dir, outdir='afni_boutiques'):
    """
    Generates ``boutiques`` descriptors for each AFNI command in `help_dir`

    Parameters
    ----------
    help_dir : str
        Path to directory with AFNI help files
    outdir : str
        Path to directory where generated ``boutiques`` descriptors should be
        saved

    Returns
    -------
    descriptors : list
        List of paths to generated boutiques descriptor JSON files
    """
    outdir = gen_outdir(outdir)
    help_dir = Path(help_dir).resolve()

    descriptors = []
    for tool in help_dir.glob('*.complete.bash'):
        cmd = tool.name.replace('.complete.bash', '')
        help_fname = get_help_fname(help_dir, cmd)
        out_fname = outdir.joinpath('{}.json'.format(cmd))

        # get hypothetical parameters (both flag and positional!)
        params = get_full_help(help_fname,
                               putative=get_complete_args(tool))[0]
        params += [{'param': f} for f in get_usage_params(help_fname)]

        # construct an empty parser to hold all parameters
        parser = argparse.ArgumentParser(add_help=False)
        for param in params:
            # ensure argument not already in parser (and not invalid / empty)
            arg = param.get('param')
            previous = [f.option_strings for f in parser._actions] + [['']]

            if arg not in list(chain.from_iterable(previous)):
                # get info about parameter, if we have it
                kwargs = {'required': True} if arg == '-input' else {}
                kwargs.update({'dest': '__{}__'.format(arg.strip('-').upper())}
                              if arg.startswith('-') else {})
                desc = param.get('help', 'NA')
                if desc != 'NA':
                    desc = ' '.join([f.strip() for f in desc.split('\n')])

                # add parameter to parser
                parser.add_argument(arg, type=str, help=desc, **kwargs)

        # save out new boutiques descriptor
        bout = bc.CreateDescriptor(parser, execname=cmd)
        bout.save(out_fname)
        descriptors.append(out_fname.as_posix())

    return descriptors


def fix_boutify_help(boutified, descdir, outdir):
    """
    Parameters
    ----------
    boutified : str
        Path to file from Firebase with updated help annotations
    descdir : str
        Path to directory where JSON files to boutify were kept
    outdir : str
        Path to directory with boutiques descriptors whose help should be
        updated
    """
    descdir, outdir = Path(descdir), Path(outdir)

    # load in boutified annotations
    with open(boutified) as src:
        annotations = json.load(src)

    # iterate through all annnotations
    for prefix, update in annotations.items():
        # load in un-boutified JSON and boutiques descriptor for updating
        desc_fname = descdir.joinpath('{}.json'.format(prefix))
        out_fname = outdir.joinpath('{}.json'.format(
            PARTJSON.sub('', prefix).replace('_py', '.py'))
        )
        # if we don't have both then skip this annotation, I guess
        if not desc_fname.exists() or not out_fname.exists():
            continue
        with desc_fname.open() as boutified_help:
            info = json.load(boutified_help)
        with out_fname.open() as boutiques_descriptor:
            descriptor = json.load(boutiques_descriptor)

        # pull relevant info from annotation, helptext, and boutiques desc
        update = update.get('annot')
        if update is None:
            continue
        helptext = '\n'.join(info['helptext'])
        flags = [t.get('command-line-flag') for t in descriptor['inputs']]

        # go through parameters and update help in boutiques descriptor
        remove_inputs = []
        for n, param in enumerate(info['params']):
            # if there is NO help_range provided in the annotation then this
            # means we mis-classified the parameter and it should be removed
            help_ranges = update.get('h{}'.format(n))
            if help_ranges is None:
                remove_inputs += [n]
                continue

            # get the parameter name and boutified parameter description/help
            # clean up help by:
            #   1. stripping whitespace from highlight chunks
            #   2. joining higlights chunks with a space
            #   3. splitting joined text into lines
            #   4. condensing consecutive whitespace in each line
            #   5. stripping whitespace from each line
            #   6. rejoining lines with a space
            param_name = helptext[slice(*param['param_range'])]
            param_desc = ' '.join([helptext[start:end].strip() for start, end
                                   in help_ranges]).splitlines()
            param_desc = ' '.join([WHISPACE.sub(' ', f).strip()
                                   for f in param_desc])

            # reassign parameter description to the relevant boutiques input
            descriptor_index = flags.index(param_name)
            descriptor['inputs'][descriptor_index]['description'] = param_desc

        # remove all the "bad" parameters from both the inputs and command line
        for idx in sorted(remove_inputs, reverse=True):
            removed = descriptor['inputs'].pop(idx)
            new = re.sub(removed['id'] + ' ', '', descriptor['command-line'])
            descriptor['command-line'] = new

        # write out updated descriptor information
        with out_fname.open('w') as dest:
            json.dump(descriptor, dest, indent=4, sort_keys=True)
